# Copyright NGGT.LightKeeper. All Rights Reserved.

import os
import sys


# Run Django administrative tasks with the project settings, with a clear error when Django is missing.
def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "PULSEHR.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    execute_from_command_line(sys.argv)


# Run: python manage.py <command>
if __name__ == "__main__":
    main()
