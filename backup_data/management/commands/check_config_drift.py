import os
import tempfile
from django.core.management.base import BaseCommand
from backup_data.models import RouterBackup
from router_manager.models import Router
from routerlib.functions import (
    connect_to_ssh,
    get_router_backup_file_extension,
    execute_cisco_commands,
    execute_huawei_commands,
    execute_zte_commands,
)
from routerlib.config_normalizer import normalize_config
from scp import SCPClient


class Command(BaseCommand):
    help = 'Checks for unsaved changes (config drift) in specific or all routers'

    def handle(self, *args, **options):
        self.stdout.write('Starting Config Drift Check...')
        routers = Router.objects.filter(enabled=True).exclude(router_type='monitoring')
        for router in routers:
            ssh_client = None
            try:
                latest_backup = RouterBackup.objects.filter(router=router, success=True).order_by('-created').first()
                if not latest_backup or not latest_backup.backup_text:
                    self.stdout.write(f'No prior successful backup found for {router.name}. Skipping drift check.')
                    continue

                file_extension = get_router_backup_file_extension(router.router_type)
                protocol = (getattr(router, 'connection_protocol', 'ssh') or 'ssh').lower()
                rsc_content_cleaned = ''

                if router.router_type in ['mikrotik', 'mikrotik-branded']:
                    ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
                    command = f'/export file=drift_check_{router.uuid}.{file_extension["text"]} terse'
                    stdin, stdout, stderr = ssh_client.exec_command(command)
                    stdout.read()

                    rsc_file_path = os.path.join(tempfile.gettempdir(), f'drift_check_{router.uuid}.{file_extension["text"]}')
                    scp_client = SCPClient(ssh_client.get_transport(), socket_timeout=60)
                    scp_client.get(f'/drift_check_{router.uuid}.{file_extension["text"]}', rsc_file_path)

                    with open(rsc_file_path, 'r', encoding='utf-8', errors='replace') as rsc_file:
                        rsc_content = rsc_file.read()
                        rsc_content_cleaned = '\n'.join(
                            line for line in rsc_content.split('\n') if not line.strip().startswith('#')
                        )

                    os.remove(rsc_file_path)
                    command = f'/file remove "drift_check_{router.uuid}.{file_extension["text"]}"'
                    ssh_client.exec_command(command)

                elif router.router_type == 'cisco-ios':
                    outputs = execute_cisco_commands(
                        router.address, router.port, router.username, router.password,
                        ['show running-config'], protocol=protocol, sshkey=router.ssh_key, timeout=45
                    )
                    rsc_content_cleaned = outputs.get('show running-config', '')

                elif router.router_type == 'huawei':
                    outputs = execute_huawei_commands(
                        router.address, router.port, router.username, router.password,
                        ['display current-configuration'], protocol=protocol, sshkey=router.ssh_key, timeout=60
                    )
                    rsc_content_cleaned = outputs.get('display current-configuration', '')

                elif router.router_type == 'zte':
                    outputs = execute_zte_commands(
                        router.address, router.port, router.username, router.password,
                        ['show running-config'], protocol=protocol, sshkey=router.ssh_key, timeout=60
                    )
                    rsc_content_cleaned = outputs.get('show running-config', '')

                elif router.router_type == 'openwrt':
                    ssh_client = connect_to_ssh(router.address, router.port, router.username, router.password, router.ssh_key)
                    stdin, stdout, stderr = ssh_client.exec_command('uci export')
                    rsc_content_cleaned = stdout.read().decode('utf-8', errors='replace')

                else:
                    self.stdout.write(f'Router type {router.router_type} unsupported for drift check.')
                    continue

                norm_current = normalize_config(rsc_content_cleaned, router.router_type)
                norm_latest = normalize_config(latest_backup.backup_text, router.router_type)

                if norm_current != norm_latest:
                    self.stdout.write(self.style.WARNING(f'Config Drift Detected on {router.name}'))
                else:
                    self.stdout.write(self.style.SUCCESS(f'{router.name} is synchronized.'))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error checking {router.name}: {str(e)}'))
            finally:
                if ssh_client:
                    try:
                        ssh_client.close()
                    except Exception:
                        pass

        self.stdout.write('Config Drift Check Complete.')
