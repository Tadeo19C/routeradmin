import re
from django.db import migrations, models


def migrate_uppercase_nodes_and_scopes(apps, schema_editor):
    RouterGroup = apps.get_model('router_manager', 'RouterGroup')
    Router = apps.get_model('router_manager', 'Router')

    seen_upper = {}
    for grp in RouterGroup.objects.all().order_by('id'):
        clean_upper = re.sub(r'\s+', ' ', (grp.name or '').strip()).upper()
        if not clean_upper:
            clean_upper = f'NODO_{grp.id}'

        if clean_upper in seen_upper:
            keeper = seen_upper[clean_upper]
            for r in grp.routers.all():
                keeper.routers.add(r)
            if grp.default_group and not keeper.default_group:
                keeper.default_group = True
                keeper.save(update_fields=['default_group'])
            grp.delete()
        else:
            if grp.name != clean_upper:
                # Evitar colisión temporal si otro registro aún sin procesar tiene exactamente clean_upper
                clash = RouterGroup.objects.filter(name=clean_upper).exclude(pk=grp.pk).first()
                if clash:
                    for r in clash.routers.all():
                        grp.routers.add(r)
                    clash.delete()
                grp.name = clean_upper
                grp.save(update_fields=['name'])
            seen_upper[clean_upper] = grp

    for r in Router.objects.all():
        has_client = r.clients.exists()
        has_group = r.routergroup_set.exists()
        new_scope = 'client' if (has_client and not has_group) else 'node'
        if r.device_scope != new_scope:
            r.device_scope = new_scope
            r.save(update_fields=['device_scope'])


class Migration(migrations.Migration):

    dependencies = [
        ('router_manager', '0035_alter_router_router_type'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='router',
            options={'verbose_name': 'Dispositivo', 'verbose_name_plural': 'Dispositivos'},
        ),
        migrations.AddField(
            model_name='router',
            name='device_scope',
            field=models.CharField(
                choices=[('node', 'Nodo'), ('client', 'Cliente')],
                db_index=True,
                default='node',
                max_length=16,
            ),
        ),
        migrations.RunPython(migrate_uppercase_nodes_and_scopes, migrations.RunPython.noop),
    ]
