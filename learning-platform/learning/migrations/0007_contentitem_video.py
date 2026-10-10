from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('learning', '0006_content_items')]

    operations = [
        migrations.AlterField(
            model_name='contentitem', name='kind',
            field=models.CharField(max_length=12, choices=[
                ('folder', 'Folder'), ('file', 'File / presentation'), ('video', 'Video'),
                ('page', 'Page'), ('link', 'Link'), ('test', 'Quiz / test'),
            ]),
        ),
    ]
