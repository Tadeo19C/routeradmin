"""
Motor de Monitoreo Activo Integrado para MEGACOM.
Realiza sondeos concurrentes (TCP Socket al puerto de gestión + Fallback ICMP Ping)
para actualizar en tiempo real el estado Online/Offline, registrar tiempos de caída
reales (RouterDownTime) y disparar alertas de cambio de estado.
"""
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Tuple
from django.db import transaction
from django.utils import timezone

from router_manager.models import Router, RouterStatus
from monitoring.models import RouterDownTime
from routerfleet_tools.models import WebadminSettings
from message_center.functions import notify_router_status_update
from dashboard.models import ActivityLog


def probe_router_reachability(address: str, port: int = 22, timeout: float = 2.5) -> bool:
    """
    Verifica si un equipo responde por su puerto TCP de gestión (SSH/Telnet)
    y, como respaldo, mediante ping ICMP.
    """
    port_num = int(port) if port else 22
    # 1. Sondeo rápido por socket TCP al puerto configurado (ej. 22 o 23)
    try:
        with socket.create_connection((address, port_num), timeout=timeout):
            return True
    except Exception:
        pass

    # 2. Fallback: Ping ICMP del sistema operativo
    try:
        if os.name == 'nt':
            cmd = ['ping', '-n', '1', '-w', str(int(timeout * 1000)), address]
        else:
            cmd = ['ping', '-c', '1', '-W', str(max(1, int(timeout))), address]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout + 1.5)
        return res.returncode == 0
    except Exception:
        return False


def _probe_single_router(router_info: Tuple[int, str, int]) -> Tuple[int, bool]:
    router_id, address, port = router_info
    is_online = probe_router_reachability(address, port, timeout=2.5)
    return router_id, is_online


def service_check_all_routers_status() -> Dict[str, Any]:
    """
    Ejecuta el sondeo concurrente de todos los equipos monitoreados y actualiza
    RouterStatus y RouterDownTime cuando ocurre una transición Online <-> Offline.
    """
    routers = list(
        Router.objects.filter(enabled=True, monitoring=True).values_list('id', 'address', 'port')
    )
    summary = {
        'checked': len(routers),
        'online': 0,
        'offline': 0,
        'status_changes': 0,
    }
    if not routers:
        return summary

    results: Dict[int, bool] = {}
    max_workers = min(15, len(routers))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_probe_single_router, r) for r in routers]
        for future in as_completed(futures):
            try:
                r_id, online = future.result()
                results[r_id] = online
            except Exception:
                pass

    now = timezone.now()
    for r_id, is_online in results.items():
        if is_online:
            summary['online'] += 1
        else:
            summary['offline'] += 1

        try:
            with transaction.atomic():
                router = Router.objects.select_for_update().get(id=r_id)
                status_obj, _ = RouterStatus.objects.select_for_update().get_or_create(router=router)
                was_online = status_obj.status_online

                if was_online != is_online:
                    status_obj.status_online = is_online
                    status_obj.last_status_change = now
                    status_obj.save()
                    summary['status_changes'] += 1

                    if is_online:
                        downtime = RouterDownTime.objects.select_for_update().filter(router=router, end_time=None).last()
                        if downtime:
                            downtime.end_time = now
                            downtime.save()
                        RouterDownTime.objects.filter(router=router, end_time=None).delete()
                        ActivityLog.objects.create(
                            user=None,
                            action="Equipo En Línea",
                            details=f"El equipo '{router.name}' ({router.address}) volvió a estar en línea",
                            router=router,
                        )
                    else:
                        if not RouterDownTime.objects.filter(router=router, end_time=None).exists():
                            RouterDownTime.objects.create(router=router, start_time=now)
                        ActivityLog.objects.create(
                            user=None,
                            action="Equipo Fuera de Línea",
                            details=f"El equipo '{router.name}' ({router.address}) dejó de responder al monitoreo",
                            router=router,
                        )

                    notify_router_status_update(router)
        except Exception:
            pass

    try:
        webadmin_settings, _ = WebadminSettings.objects.get_or_create(name='webadmin_settings')
        webadmin_settings.monitoring_last_run = now
        webadmin_settings.save(update_fields=['monitoring_last_run'])
    except Exception:
        pass

    return summary
