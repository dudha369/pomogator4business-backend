from tortoise import fields
from tortoise.models import Model


class MirrorBot(Model):
    owner_id = fields.BigIntField(pk=True, generated=False)
    token_encrypted = fields.BinaryField()
    bot_id = fields.BigIntField(null=True)
    bot_username = fields.CharField(max_length=255, null=True)
    created_at = fields.BigIntField()
    is_active = fields.BooleanField(default=True)

    class Meta:
        table = "mirror_bots"
