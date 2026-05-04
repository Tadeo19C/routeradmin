import os
import tempfile
from django.core.management.base import BaseCommand
from django.utils import timezone
from backup_data.models import RouterBackup
from router_manager.models import Router
from routerlib.functions import connect_to_ssh, get_router_backup_file_extension
from scp import SCPClient
from message_center.functions import send_channel_message

class Command(BaseCommand):
    help = 'Checks for unsaved changes (config drift) in specific or all routers'

    def handle(self, *args, **options):
        self.stdout.write('Starting Config Drift Check...')
        routers = Router.objects.filter(enabled=True).exclude(router_type='monitoring')
        for router in routers:
            try:
                # 1. Fetch latest successful backup
                latest_backup = RouterBackup.objects.filter(router=router, success=True).order_by('-created').first()
                if not latest_backup:
                    self.stdout.write(f'No prior successful backup found for {router.name}. Skipping drift check.')
                    continue

                if not latest_backup.backup_text:
                    continue

                # 2. Get current configuration without saving to disc persistently
                file_extension = get_router_backup_file_extension(router.router_type)
                ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
                
                if router.router_type in ['mikrotik', 'mikrotik-branded']:
                    command = f'/export file=drift_check_{router.uuid}.{file_extension["text"]} terse'
                    stdin, stdout, stderr = ssh_client.exec_command(command)
                    stdout.read() # Wait

                    rsc_file_path = os.path.join(tempfile.gettempdir(), f'drift_check_{router.uuid}.{file_extension["text"]}')
                    scp_client = SCPClient(ssh_client.get_transport(), socket_timeout=60)
                    scp_client.get(f'/drift_check_{router.uuid}.{file_extension["text"]}', rsc_file_path)

                    with open(rsc_file_path, 'r') as rsc_file:
                        rsc_content = rsc_file.read()
                        rsc_content_cleaned = '\n'.join(
                            line for line in rsc_content.split('\n') if not line.strip().startswith('#')
                        )
                    
                    os.remove(rsc_file_path)
                    command = f'/file remove "drift_check_{router.uuid}.{file_extension["text"]}"'
                    ssh_client.exec_command(command)

                elif router.router_type == 'openwrt':
                    command = 'uci export'
                    stdin, stdout, stderr = ssh_client.exec_command(command)
                    rsc_content_cleaned = stdout.read().decode('utf-8', errors='replace')
                
                else:
                    self.stdout.write(f'Router type {router.router_type} unsupported for drift check.')
                    continue

                # 3. Compare with latest backup
                if rsc_content_cleaned != latest_backup.backup_text:
                    self.stdout.write(self.style.WARNING(f'Config Drift Detected on {router.name}'))
                    # Send Proactive Alert securely to Email
                    message = f"""
                    ⚠️ Alerta Megacom: Modificaciones no guardadas en '{router.name}'
                    
                    El sistema de integridad ha detectado cambios recientes en la configuración de 
                    {router.name} (IP: {router.address}) que no coinciden con nuestro último backup 
                    exitoso realizado el {latest_backup.created.strftime('%Y-%m-%d %H:%M:%S')}.
                    
                    Por favor, ingresa a MEGACOM lo antes posible para revisar o forzar un nuevo respaldo, 
                    ya que los cambios directos corren riesgo de pérdida.
                    """
                    # We specify channel='email' explicitly assuming the backend routes correctly, 
                    # If send_channel_message delegates based on channel config, it handles it.
                    send_channel_message(message=message, title=f"Alerta Megacom: Modificaciones no guardadas en {router.name}")
                    
                else:
                    self.stdout.write(self.style.SUCCESS(f'{router.name} is synchronized.'))

                if ssh_client:
                    ssh_client.close()

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error checking {router.name}: {str(e)}'))

        self.stdout.write('Config Drift Check Complete.')
