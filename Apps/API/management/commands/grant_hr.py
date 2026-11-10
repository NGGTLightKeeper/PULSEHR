# Copyright NGGT.LightKeeper. All Rights Reserved.

from django.core.management.base import BaseCommand, CommandError
from rest_framework.exceptions import NotFound

from Apps.API import accounts


# Give the HR role to an existing account: python manage.py grant_hr <e-mail or username>.
class Command(BaseCommand):
    help = "Give the HR role to the account found by e-mail, username or verified phone."

    def add_arguments(self, parser) -> None:
        parser.add_argument("login", help="E-mail, username or verified phone of the account")

    def handle(self, *args, **options) -> None:
        try:
            user = accounts.grant_hr(options["login"])
        except NotFound:
            raise CommandError("Account not found. Register it on the site first.") from None
        self.stdout.write(self.style.SUCCESS(f"@{user.username} now has the role: {user.get_role_display()}."))
