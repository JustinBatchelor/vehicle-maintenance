from django.core.management.base import BaseCommand,CommandError
from allauth.socialaccount.models import SocialAccount

class Command(BaseCommand):
    help='Grant staff and superuser access to an existing Google account by local user ID.'
    def add_arguments(self,parser):
        parser.add_argument('user_id',type=int)
    def handle(self,*args,**options):
        account=SocialAccount.objects.filter(provider='google',user_id=options['user_id']).select_related('user').first()
        if not account or not account.user.is_active:
            raise CommandError('An active Google account with that local user ID is required.')
        user=account.user;user.is_staff=True;user.is_superuser=True;user.set_unusable_password()
        user.save(update_fields=['is_staff','is_superuser','password'])
        self.stdout.write('Administrator permissions granted to Google user ID '+str(user.pk))
