import datetime
import re
from django.utils import timezone
from backup_data.models import RouterBackup
import os
import tempfile
from scp import SCPClient
from django.core.files.base import ContentFile

import difflib
from message_center.functions import notify_backup_fail, notify_config_change
from routerlib.functions import (
    gen_backup_name,
    connect_to_ssh,
    get_router_backup_file_extension,
    execute_cisco_commands,
    execute_huawei_commands,
    execute_zte_commands,
    execute_mikrotik_telnet_commands,
)
from routerlib.config_normalizer import normalize_config
from typing import Optional, Tuple


def append_task_console_output(router_backup: RouterBackup, text: str, *, new_line: bool = True) -> None:
    if not router_backup.pk:
        return
    if new_line:
        text += "\n"

    timestamp = timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S")
    if router_backup.task_console_output is None:
        router_backup.task_console_output = ""
    router_backup.task_console_output += f'[{timestamp}] {text}'
    router_backup.save(update_fields=["task_console_output"])


def run_scp_get(scp_client: SCPClient, remote_path: str, local_path: str, router_backup: Optional["RouterBackup"] = None) -> None:
    if router_backup is not None:
        if router_backup.task_console_output is None:
            router_backup.task_console_output = ""
        append_task_console_output(router_backup, f"$ scp get {remote_path} -> {local_path}\n")

    try:
        scp_client.get(remote_path, local_path)

        if router_backup is not None:
            append_task_console_output(router_backup, "[scp_ok]\n\n")

    except Exception as e:
        if router_backup is not None:
            append_task_console_output(router_backup, f"[scp_error] {str(e)}\n\n")
        raise


def run_ssh_command(ssh_client, command: str, router_backup: Optional["RouterBackup"] = None, *, skip_stdout: bool = False, timeout: int = 60) -> Tuple[int, str, str]:
    if router_backup is not None:
        if router_backup.task_console_output is None:
            router_backup.task_console_output = ""
        append_task_console_output(router_backup, f"$ {command}\n")

    stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
    try:
        stdout.channel.settimeout(timeout)
        stderr.channel.settimeout(timeout)
    except Exception:
        pass

    exit_code = stdout.channel.recv_exit_status()
    stdout_text = stdout.read().decode("utf-8", errors="replace")
    stderr_text = stderr.read().decode("utf-8", errors="replace")

    if router_backup is not None:
        if skip_stdout:
            if stdout_text:
                append_task_console_output(router_backup, "[stdout suppressed]\n")
        else:
            if stdout_text:
                append_task_console_output(router_backup, stdout_text.rstrip("\n") + "\n")

        if stderr_text:
            append_task_console_output(router_backup, "[stderr]\n" + stderr_text.rstrip("\n") + "\n")

        append_task_console_output(router_backup, f"[exit_code={exit_code}]\n\n")
        router_backup.save(update_fields=["task_console_output"])

    return exit_code, stdout_text, stderr_text


def _has_real_config_change(router, current_text: str, current_backup_id: int) -> Tuple[bool, Optional[RouterBackup]]:
    """
    Verifica si la configuración actual presenta un cambio real respecto al último
    respaldo exitoso del mismo router utilizando normalización inteligente.
    Retorna (True, None) si es el primer respaldo o si hubo cambio real.
    Retorna (False, previous_backup) si la configuración es idéntica.
    """
    previous_backup = (
        RouterBackup.objects.filter(router=router, success=True)
        .exclude(id=current_backup_id)
        .order_by('-created')
        .first()
    )
    if not previous_backup or not previous_backup.backup_text:
        return True, None

    norm_current = normalize_config(current_text, router.router_type)
    norm_prev = normalize_config(previous_backup.backup_text, router.router_type)

    if norm_current == norm_prev:
        return False, previous_backup
    return True, previous_backup


def perform_backup(router_backup: RouterBackup):
    if router_backup.success or router_backup.error:
        router_backup.router.routerstatus.backup_lock = None
        router_backup.router.routerstatus.save()
        return
    if not router_backup.router.backup_profile:
        router_backup.error = True
        router_backup.error_message = "No backup profile assigned"
        router_backup.save()
        router_backup.router.routerstatus.backup_lock = None
        router_backup.router.routerstatus.save()
        notify_backup_fail(router_backup)
        return
    if router_backup.retry_count > router_backup.router.backup_profile.max_retry:
        router_backup.error = True
        router_backup.save()
        router_backup.router.routerstatus.backup_lock = None
        router_backup.router.routerstatus.save()
        notify_backup_fail(router_backup)
        return

    if router_backup.backup_pending_retrieval:
        backup_success, error_message = retrieve_backup(router_backup)
        if error_message:
            handle_backup_failure(router_backup, error_message)
            return

        if backup_success:
            clean_up_backup_files(router_backup)
            router = router_backup.router

            # Si NO hubo cambio real respecto al último respaldo exitoso,
            # actualizamos la marca de tiempo de verificación y descartamos el registro duplicado.
            if router_backup.identical_to_previous:
                router.routerstatus.last_backup = timezone.now()
                router.routerstatus.last_backup_failed = None
                router.routerstatus.backup_lock = None
                router.routerstatus.save()

                prev = (
                    RouterBackup.objects.filter(router=router, success=True)
                    .exclude(id=router_backup.id)
                    .order_by('-created')
                    .first()
                )
                if prev:
                    prev.updated = timezone.now()
                    prev.save(update_fields=['updated'])

                if router_backup.backup_binary:
                    try:
                        router_backup.backup_binary.delete(save=False)
                    except Exception:
                        pass
                router_backup.delete()
                return

            if router_backup.schedule_time:
                start_time = router_backup.schedule_time
            else:
                start_time = router_backup.created
            router_backup.queue_length = (timezone.now() - start_time).seconds
            prev_backup = (
                RouterBackup.objects.filter(router=router, success=True)
                .exclude(id=router_backup.id)
                .order_by('-created')
                .first()
            )
            router_backup.finish_time = timezone.now()
            router_backup.backup_pending_retrieval = False
            router_backup.error_message = ''
            router_backup.success = True
            router_backup.save()
            router.routerstatus.last_backup = timezone.now()
            router.routerstatus.last_backup_failed = None
            router.routerstatus.backup_lock = None
            router.routerstatus.save()

            # Si existía un respaldo previo y este nuevo respaldo se guardó, hubo un cambio real:
            if prev_backup and prev_backup.backup_text and router_backup.backup_text:
                try:
                    norm_prev = normalize_config(prev_backup.backup_text, router.router_type).splitlines()
                    norm_curr = normalize_config(router_backup.backup_text, router.router_type).splitlines()
                    diff_lines = list(difflib.unified_diff(norm_prev, norm_curr, lineterm=''))
                    added = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
                    removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
                    if added > 0 or removed > 0:
                        notify_config_change(router_backup, prev_backup, added_lines=added, removed_lines=removed)
                except Exception:
                    pass
        else:
            handle_backup_failure(router_backup, error_message)
    else:
        backup_success, backup_files, error_message = execute_backup(router_backup)
        if backup_success:
            # Para equipos donde execute_backup ya obtiene la configuración completa (Cisco IOS, Huawei VRP, ZTE o Telnet),
            # completamos en un solo paso sin esperar retrieve_interval.
            protocol = (getattr(router_backup.router, 'connection_protocol', 'ssh') or 'ssh').lower()
            if router_backup.router.router_type in ('cisco-ios', 'huawei', 'zte') or protocol == 'telnet':
                router_backup.backup_pending_retrieval = True
                router_backup.save()
                perform_backup(router_backup)
                return

            router_backup.backup_pending_retrieval = True
            router_backup.error_message = ''
            router_backup.retry_count = 0
            router_backup.next_retry = timezone.now() + datetime.timedelta(seconds=router_backup.router.backup_profile.retrieve_interval)
            router_backup.save()
        else:
            handle_backup_failure(router_backup, error_message)
    return


def handle_backup_failure(router_backup: RouterBackup, error_message):
    router_backup.error_message = error_message
    router_backup.retry_count += 1
    router_backup.next_retry = timezone.now() + datetime.timedelta(minutes=router_backup.router.backup_profile.retry_interval)
    router_backup.save()
    append_task_console_output(router_backup, f"Backup failed: {error_message}")


def execute_backup(router_backup: RouterBackup):
    append_task_console_output(router_backup, '=== Starting remote backup ===')
    error_message = ""
    router = router_backup.router
    backup_name = gen_backup_name(router_backup)
    file_extension = get_router_backup_file_extension(router.router_type)
    protocol = (getattr(router, 'connection_protocol', 'ssh') or 'ssh').lower()
    ssh_client = None
    additional_parameters = ""
    try:
        if router.router_type in ('mikrotik', 'mikrotik-branded'):
            if router.backup_profile:
                if router.backup_profile.parameter_sensitive:
                    additional_parameters += ' show-sensitive'
                if router.backup_profile.parameter_terse:
                    additional_parameters += ' terse'

            if protocol == 'telnet':
                cmd = f'/export{additional_parameters}'
                append_task_console_output(router_backup, f'$ {cmd} (via Telnet)')
                outputs = execute_mikrotik_telnet_commands(
                    router.address, router.port, router.username, router.password, [cmd], timeout=45
                )
                raw_export = outputs.get(cmd, '')
                cleaned = '\n'.join(
                    line for line in raw_export.split('\n') if not line.strip().startswith('#')
                ).strip()
                if not cleaned:
                    return False, [], "Failed to execute MikroTik Telnet backup: Empty configuration"

                has_change, _ = _has_real_config_change(router, cleaned, router_backup.id)
                if not has_change:
                    router_backup.identical_to_previous = True
                    append_task_console_output(router_backup, '[Deduplication] Configuration matches previous backup (normalized).')
                else:
                    router_backup.backup_text = cleaned
                    router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                    router_backup.backup_binary.save(
                        f"{backup_name}.{file_extension['binary']}",
                        ContentFile(raw_export.encode('utf-8'))
                    )
                router_backup.save()
                return True, [f'{backup_name}.{file_extension["text"]}'], error_message

            ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
            command = f'/system backup save name={backup_name}.{file_extension["binary"]}'
            run_ssh_command(ssh_client, command, router_backup)
            command = f'/export file={backup_name}.{file_extension["text"]} {additional_parameters}'
            run_ssh_command(ssh_client, command, router_backup)
            return True, [f'{backup_name}.{file_extension["binary"]}', f'{backup_name}.{file_extension["text"]}'], error_message

        elif router.router_type == 'openwrt':
            ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
            command = 'uci export'
            exit_code, stdout_text, stderr_text = run_ssh_command(ssh_client, command, router_backup, skip_stdout=True)
            backup_text = stdout_text
            if backup_text:
                router_backup.backup_text = backup_text
                router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                router_backup.save()
            else:
                return False, [], "Failed to execute backup: Empty backup text"
            command = f'sysupgrade --create-backup /tmp/{backup_name}.{file_extension["binary"]}'
            run_ssh_command(ssh_client, command, router_backup)
            return True, [f'/tmp/{backup_name}.{file_extension["binary"]}', f'{backup_name}.{file_extension["text"]}'], error_message

        elif router.router_type == 'ubiquiti-airos':
            append_task_console_output(router_backup, '=== Skipping remote backup (airOS uses existing /tmp/system.cfg) ===')
            return True, ['/tmp/system.cfg'], error_message

        elif router.router_type == 'cisco-ios':
            append_task_console_output(router_backup, f'$ show running-config (via {protocol.upper()})')
            outputs = execute_cisco_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['show running-config'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=45
            )
            stdout_text = outputs.get('show running-config', '')
            clean_text = re.sub(r'^Building configuration.*?\n', '', stdout_text, flags=re.MULTILINE).strip()

            if not clean_text or 'invalid autocommand' in clean_text.lower() or '% invalid input' in clean_text.lower():
                return False, [], "No se pudo obtener show running-config (verifique privilegios enable en el equipo Cisco)"

            append_task_console_output(router_backup, '[stdout retrieved successfully]')

            has_change, _ = _has_real_config_change(router, clean_text, router_backup.id)
            if not has_change:
                router_backup.identical_to_previous = True
                append_task_console_output(router_backup, '[Deduplication] Configuration matches previous backup (normalized).')
            else:
                router_backup.backup_text = clean_text
                router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                router_backup.backup_binary.save(
                    f"{backup_name}.{file_extension['binary']}",
                    ContentFile(clean_text.encode('utf-8'))
                )
            router_backup.save()
            return True, [f'{backup_name}.{file_extension["text"]}'], error_message

        elif router.router_type == 'huawei':
            append_task_console_output(router_backup, f'$ display current-configuration (via {protocol.upper()})')
            outputs = execute_huawei_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['display current-configuration'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=60
            )
            stdout_text = outputs.get('display current-configuration', '')
            clean_text = stdout_text.strip()

            if not clean_text or 'error:' in clean_text.lower()[:80] or 'unrecognized command' in clean_text.lower():
                return False, [], "No se pudo obtener display current-configuration del equipo Huawei VRP"

            append_task_console_output(router_backup, '[stdout retrieved successfully]')

            has_change, _ = _has_real_config_change(router, clean_text, router_backup.id)
            if not has_change:
                router_backup.identical_to_previous = True
                append_task_console_output(router_backup, '[Deduplication] Configuration matches previous backup (normalized).')
            else:
                router_backup.backup_text = clean_text
                router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                router_backup.backup_binary.save(
                    f"{backup_name}.{file_extension['binary']}",
                    ContentFile(clean_text.encode('utf-8'))
                )
            router_backup.save()
            return True, [f'{backup_name}.{file_extension["text"]}'], error_message

        elif router.router_type == 'zte':
            append_task_console_output(router_backup, f'$ show running-config (via {protocol.upper()})')
            outputs = execute_zte_commands(
                router.address,
                router.port,
                router.username,
                router.password,
                ['show running-config'],
                protocol=protocol,
                sshkey=router.ssh_key,
                enable_password=router.enable_password,
                timeout=60
            )
            stdout_text = outputs.get('show running-config', '')
            clean_text = re.sub(r'^Building configuration.*?\n', '', stdout_text, flags=re.MULTILINE).strip()

            if not clean_text or '% invalid input' in clean_text.lower() or 'error:' in clean_text.lower()[:80]:
                return False, [], "No se pudo obtener show running-config del equipo ZTE"

            append_task_console_output(router_backup, '[stdout retrieved successfully]')

            has_change, _ = _has_real_config_change(router, clean_text, router_backup.id)
            if not has_change:
                router_backup.identical_to_previous = True
                append_task_console_output(router_backup, '[Deduplication] Configuration matches previous backup (normalized).')
            else:
                router_backup.backup_text = clean_text
                router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                router_backup.backup_binary.save(
                    f"{backup_name}.{file_extension['binary']}",
                    ContentFile(clean_text.encode('utf-8'))
                )
            router_backup.save()
            return True, [f'{backup_name}.{file_extension["text"]}'], error_message

        else:
            error_message = f"Router type not supported: {router_backup.router.get_router_type_display()}"
            return False, [], error_message
    except Exception as e:
        error_message = f"Failed to execute backup: {str(e)}"
        return False, [], error_message
    finally:
        if ssh_client:
            ssh_client.close()


def retrieve_backup(router_backup: RouterBackup):
    append_task_console_output(router_backup, '=== Retrieving backup files ===')
    error_message = ""
    router = router_backup.router
    backup_name = gen_backup_name(router_backup)
    success = False
    file_extension = get_router_backup_file_extension(router.router_type)
    protocol = (getattr(router, 'connection_protocol', 'ssh') or 'ssh').lower()
    ssh_client = None

    try:
        if router.router_type in ('mikrotik', 'mikrotik-branded'):
            if protocol == 'telnet':
                return True, ''

            rsc_file_path = os.path.join(tempfile.gettempdir(), f'{backup_name}.{file_extension["text"]}')
            backup_file_path = os.path.join(tempfile.gettempdir(), f'{backup_name}.{file_extension["binary"]}')
            ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
            scp_client = SCPClient(ssh_client.get_transport(), socket_timeout=300)
            run_scp_get(scp_client, f'/{backup_name}.{file_extension["text"]}', rsc_file_path, router_backup)

            with open(rsc_file_path, 'r', encoding='utf-8', errors='replace') as rsc_file:
                rsc_content = rsc_file.read()
                rsc_content_cleaned = '\n'.join(
                    line for line in rsc_content.split('\n') if not line.strip().startswith('#')
                )

                if not rsc_content_cleaned.strip():
                    return False, "Failed to execute backup: Retrieved empty configuration text."

                has_change, _ = _has_real_config_change(router, rsc_content_cleaned, router_backup.id)
                if not has_change:
                    router_backup.identical_to_previous = True
                    append_task_console_output(router_backup, '[Deduplication] Configuration matches previous backup (normalized). Skipping duplicate storage.')
                else:
                    run_scp_get(scp_client, f'/{backup_name}.{file_extension["binary"]}', backup_file_path, router_backup)
                    router_backup.backup_text = rsc_content_cleaned
                    router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                    with open(backup_file_path, 'rb') as backup_file:
                        router_backup.backup_binary.save(
                            f"{backup_name}.{file_extension['binary']}",
                            ContentFile(backup_file.read())
                        )
                    if os.path.exists(backup_file_path):
                        os.remove(backup_file_path)

            router_backup.save()
            if os.path.exists(rsc_file_path):
                os.remove(rsc_file_path)

            command = f'/file remove "{backup_name}.{file_extension["text"]}"'
            run_ssh_command(ssh_client, command, router_backup)
            command = f'/file remove "{backup_name}.{file_extension["binary"]}"'
            run_ssh_command(ssh_client, command, router_backup)
            success = True

        elif router.router_type == 'openwrt':
            has_change, _ = _has_real_config_change(router, router_backup.backup_text or '', router_backup.id)
            if not has_change:
                router_backup.identical_to_previous = True
                router_backup.save()
            else:
                remote_backup_file_path = f'/tmp/{backup_name}.{file_extension["binary"]}'
                local_backup_file_path = os.path.join(tempfile.gettempdir(), f'{backup_name}.{file_extension["binary"]}')
                ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
                scp_client = SCPClient(ssh_client.get_transport(), socket_timeout=300)
                run_scp_get(scp_client, remote_backup_file_path, local_backup_file_path, router_backup)
                with open(local_backup_file_path, 'rb') as backup_file:
                    router_backup.backup_binary.save(f"{backup_name}.{file_extension['binary']}", ContentFile(backup_file.read()))
                router_backup.save()
                os.remove(local_backup_file_path)
                command = f'rm {remote_backup_file_path}'
                run_ssh_command(ssh_client, command, router_backup)
            success = True

        elif router.router_type == 'ubiquiti-airos':
            remote_path = '/tmp/system.cfg'
            local_path = os.path.join(tempfile.gettempdir(), f'{backup_name}.{file_extension["text"]}')
            ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
            scp_client = SCPClient(ssh_client.get_transport(), socket_timeout=300)
            run_scp_get(scp_client, remote_path, local_path, router_backup)
            with open(local_path, 'rb') as f:
                raw_bytes = f.read()

            try:
                text = raw_bytes.decode('utf-8')
                append_task_console_output(router_backup, '[decode=utf-8]')
            except UnicodeDecodeError:
                text = raw_bytes.decode('latin-1', errors='replace')
                append_task_console_output(router_backup, '[decode=latin-1 fallback]')

            if not text.strip():
                return False, "Failed to execute backup: Retrieved empty configuration text."

            has_change, _ = _has_real_config_change(router, text, router_backup.id)
            if not has_change:
                router_backup.identical_to_previous = True
                append_task_console_output(router_backup, '[Deduplication] Configuration matches previous backup (normalized).')
            else:
                router_backup.backup_text = text
                router_backup.backup_text_filename = f'{backup_name}.{file_extension["text"]}'
                router_backup.backup_binary.save(
                    f"{backup_name}.{file_extension['binary']}",
                    ContentFile(raw_bytes)
                )
            router_backup.save()
            os.remove(local_path)
            success = True

        elif router.router_type in ('cisco-ios', 'huawei', 'zte'):
            if router_backup.identical_to_previous or router_backup.backup_text:
                success = True
            else:
                error_message = 'Backup text not found'

        else:
            error_message = f"Router type not supported: {router_backup.router.get_router_type_display()}"
            return success, error_message

    except Exception as e:
        return success, f"Failed to retrieve backup files: {str(e)}"
    finally:
        if ssh_client:
            ssh_client.close()

    return success, error_message


def clean_up_backup_files(router_backup: RouterBackup):
    append_task_console_output(router_backup, '=== Cleaning up leftover backup files on the router ===')
    router = router_backup.router
    protocol = (getattr(router, 'connection_protocol', 'ssh') or 'ssh').lower()
    ssh_client = None
    try:
        if router.router_type in ('mikrotik', 'mikrotik-branded') and protocol == 'ssh':
            ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
            command = 'file remove [find where name~"routerfleet-backup-"]'
            run_ssh_command(ssh_client, command, router_backup)
        elif router.router_type == 'openwrt' and protocol == 'ssh':
            ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
            command = 'rm /tmp/routerfleet-backup-*'
            run_ssh_command(ssh_client, command, router_backup)
        else:
            return
    except Exception as e:
        append_task_console_output(router_backup, f"Failed to clean up backup files: {str(e)}")
    finally:
        if ssh_client:
            ssh_client.close()
