import datetime
import threading
from django.db.models import Q
from django.utils import timezone

from fleet_commander.models import CommandJob, CommandSchedule, CommandTask, CommandVariant
from router_manager.models import RouterStatus
from routerlib.functions import (
    connect_to_ssh,
    execute_cisco_commands,
    execute_huawei_commands,
    execute_zte_commands,
    execute_mikrotik_telnet_commands,
)


def run_fleet_ssh_command(ssh_client, command, timeout=45):
    stdin, stdout, stderr = ssh_client.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    stdout_text = stdout.read().decode("utf-8", errors="replace")
    stderr_text = stderr.read().decode("utf-8", errors="replace")
    return exit_code, stdout_text, stderr_text


def execute_command_task(task):
    command = task.job.command
    router = task.router

    if not router:
        task.status = 'error'
        task.error_message = 'Router no longer exists'
        task.finished_at = timezone.now()
        task.save()
        return

    router_status, _ = RouterStatus.objects.get_or_create(router=router)
    router_status.command_lock = timezone.now()
    router_status.save(update_fields=['command_lock'])

    ssh_client = None
    try:
        task.started_at = timezone.now()
        task.status = 'pending'
        task.retry_count += 1
        if task.retry_count > command.max_retry:
            task.status = 'error'
            task.error_message = task.error_message or 'Max retries reached'
            task.finished_at = timezone.now()
            task.save(update_fields=['started_at', 'status', 'retry_count', 'error_message', 'finished_at'])
            return
        task.save(update_fields=['started_at', 'status', 'retry_count'])

        variant = task.command_variant
        if not variant:
            try:
                variant = CommandVariant.objects.get(
                    command=command, router_type=router.router_type, enabled=True
                )
                task.command_variant = variant
            except CommandVariant.DoesNotExist:
                task.status = 'error'
                task.error_message = f'No enabled variant for router type: {router.router_type}'
                task.finished_at = timezone.now()
                return

        task.command_payload = variant.payload
        task.save(update_fields=['command_variant', 'command_payload'])

        payload_lines = [line.strip() for line in variant.payload.strip().splitlines() if line.strip()]
        protocol = (getattr(router, 'connection_protocol', 'ssh') or 'ssh').lower()
        all_stdout = []
        last_exit_code = 0

        if router.router_type == 'cisco-ios':
            outputs = execute_cisco_commands(
                router.address, router.port, router.username, router.password,
                payload_lines, protocol=protocol, sshkey=router.ssh_key,
                enable_password=router.enable_password, timeout=45
            )
            for cmd_line in payload_lines:
                out_str = outputs.get(cmd_line, '')
                if out_str:
                    all_stdout.append(f"$ {cmd_line}\n{out_str}")

        elif router.router_type == 'huawei':
            outputs = execute_huawei_commands(
                router.address, router.port, router.username, router.password,
                payload_lines, protocol=protocol, sshkey=router.ssh_key,
                enable_password=router.enable_password, timeout=45
            )
            for cmd_line in payload_lines:
                out_str = outputs.get(cmd_line, '')
                if out_str:
                    all_stdout.append(f"$ {cmd_line}\n{out_str}")

        elif router.router_type == 'zte':
            outputs = execute_zte_commands(
                router.address, router.port, router.username, router.password,
                payload_lines, protocol=protocol, sshkey=router.ssh_key,
                enable_password=router.enable_password, timeout=45
            )
            for cmd_line in payload_lines:
                out_str = outputs.get(cmd_line, '')
                if out_str:
                    all_stdout.append(f"$ {cmd_line}\n{out_str}")

        elif router.router_type in ('mikrotik', 'mikrotik-branded') and protocol == 'telnet':
            outputs = execute_mikrotik_telnet_commands(
                router.address, router.port, router.username, router.password,
                payload_lines, timeout=45
            )
            for cmd_line in payload_lines:
                out_str = outputs.get(cmd_line, '')
                if out_str:
                    all_stdout.append(f"$ {cmd_line}\n{out_str}")

        else:
            ssh_client = connect_to_ssh(
                router.address, router.port, router.username, router.password, router.ssh_key
            )
            for line in payload_lines:
                exit_code, stdout_text, stderr_text = run_fleet_ssh_command(ssh_client, line)
                last_exit_code = exit_code
                if stdout_text:
                    all_stdout.append(stdout_text)
                if exit_code != 0:
                    task.error_message = stderr_text or f'Command exited with code {exit_code}'
                    break

        task.command_executed = '\n'.join(payload_lines)

        if command.capture_output:
            task.command_output = '\n\n'.join(all_stdout)

        if last_exit_code == 0 and not task.error_message:
            task.status = 'success'
            task.finished_at = timezone.now()
        else:
            handle_task_retry(task, command)

    except Exception as e:
        task.error_message = str(e)
        handle_task_retry(task, command)
    finally:
        if ssh_client:
            ssh_client.close()

        router_status.command_lock = None
        router_status.save(update_fields=['command_lock'])

        task.save()
        check_job_completion(task.job)


def handle_task_retry(task, command):
    if task.retry_count >= command.max_retry:
        task.status = 'error'
        task.finished_at = timezone.now()
    else:
        task.next_retry = timezone.now() + datetime.timedelta(seconds=command.retry_interval)


def check_job_completion(job):
    pending_count = job.tasks.filter(status='pending').count()
    if pending_count == 0:
        job.completed = timezone.now()
        job.save(update_fields=['completed'])


def perform_pending_command_tasks(max_execution_time=45):
    """Ejecuta las tareas de comando pendientes en la cola."""
    data = {'tasks_performed': 0}
    execution_start_time = timezone.now()

    pending_tasks = CommandTask.objects.filter(
        status='pending',
        router__routerstatus__command_lock__isnull=True,
        router__routerstatus__backup_lock__isnull=True,
    ).filter(
        Q(next_retry__isnull=True) | Q(next_retry__lte=timezone.now())
    ).select_related('job__command', 'router', 'command_variant')

    for task in pending_tasks:
        execute_command_task(task)
        data['tasks_performed'] += 1
        if timezone.now() - execution_start_time > datetime.timedelta(seconds=max_execution_time):
            break

    return data


def run_pending_command_tasks_async():
    """Dispara en segundo plano la ejecución inmediata de tareas de comando pendientes."""
    threading.Thread(target=perform_pending_command_tasks, daemon=True).start()


def create_jobs_from_schedules():
    now = timezone.now()
    data = {'jobs_created': 0, 'tasks_created': 0}

    due_schedules = CommandSchedule.objects.filter(
        enabled=True, command__enabled=True, next_run__lte=now
    ).select_related('command')

    for schedule in due_schedules:
        schedule.disable_if_invalid()
        if not schedule.enabled:
            continue

        routers = set(schedule.router.filter(enabled=True))
        for group in schedule.router_group.all():
            routers.update(group.routers.filter(enabled=True))

        if not routers:
            schedule.last_run = now
            schedule.save(update_fields=['last_run'])
            schedule.update_next_run()
            continue

        job = CommandJob.objects.create(
            command=schedule.command,
            exec_source='schedule',
        )
        data['jobs_created'] += 1

        for router in routers:
            variant = CommandVariant.objects.filter(
                command=schedule.command, router_type=router.router_type, enabled=True
            ).first()

            CommandTask.objects.create(
                job=job,
                command_variant=variant,
                router=router,
                command_payload=variant.payload if variant else '',
            )
            data['tasks_created'] += 1

        schedule.last_run = now
        schedule.save(update_fields=['last_run'])
        schedule.update_next_run()

    return data


def create_manual_job(command, routers=None, router_groups=None, user=None):
    all_routers = set()
    if routers:
        all_routers.update(routers.filter(enabled=True))
    if router_groups:
        for group in router_groups:
            all_routers.update(group.routers.filter(enabled=True))

    if not all_routers:
        return None

    job = CommandJob.objects.create(
        command=command,
        exec_source='manual',
        user_source=user,
        user_source_name=user.username if user else None,
    )

    for router in all_routers:
        variant = CommandVariant.objects.filter(
            command=command, router_type=router.router_type, enabled=True
        ).first()

        CommandTask.objects.create(
            job=job,
            command_variant=variant,
            router=router,
            command_payload=variant.payload if variant else '',
        )

    run_pending_command_tasks_async()
    return job
