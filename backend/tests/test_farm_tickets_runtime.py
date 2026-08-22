import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bot"))

from yuno_bot import main as bot_main  # noqa: E402
from yuno_bot.domain_modules.farm_tickets import runtime  # noqa: E402
from yuno_bot.platform.contracts import ActorContext  # noqa: E402


class FakeCategory:
    def __init__(self, resource_id: int, name: str) -> None:
        self.id = resource_id
        self.name = name
        self.channels: list[FakeTextChannel] = []


class FakeIdentity:
    def __init__(self, resource_id: int) -> None:
        self.id = resource_id


class FakeThread:
    def __init__(self, resource_id: int) -> None:
        self.id = resource_id
        self.sent: list[dict] = []
        self.deleted = False

    async def send(self, **kwargs):
        self.sent.append(kwargs)
        return SimpleNamespace(id=9000 + len(self.sent))

    async def delete(self, **kwargs) -> None:
        self.deleted = True


class FakeMessage:
    def __init__(self, resource_id: int, channel: "FakeTextChannel") -> None:
        self.id = resource_id
        self.channel = channel
        self.edits: list[dict] = []
        self.thread_creations = 0
        self.deleted = False

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)

    async def create_thread(self, **kwargs) -> FakeThread:
        self.thread_creations += 1
        # O Discord reutiliza o ID da mensagem inicial para a thread publica.
        thread = FakeThread(self.id)
        self.channel.guild.resources[thread.id] = thread
        return thread

    async def delete(self) -> None:
        self.deleted = True


class FakeTextChannel:
    def __init__(
        self,
        resource_id: int,
        name: str,
        guild: "FakeGuild",
        category: FakeCategory | None,
    ) -> None:
        self.id = resource_id
        self.name = name
        self.guild = guild
        self.category_id = category.id if category is not None else None
        self.permissions: list[tuple[object, dict]] = []
        self.messages: dict[int, FakeMessage] = {}
        self.edits: list[dict] = []
        self.deleted = False
        if category is not None:
            category.channels.append(self)

    async def set_permissions(self, target, **kwargs) -> None:
        self.permissions.append((target, kwargs))

    async def send(self, **kwargs) -> FakeMessage:
        resource_id = self.guild.next_id()
        message = FakeMessage(resource_id, self)
        self.messages[resource_id] = message
        return message

    async def fetch_message(self, resource_id: int) -> FakeMessage:
        return self.messages[resource_id]

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)
        category = kwargs.get("category")
        if category is not None:
            self.category_id = category.id

    async def delete(self, **kwargs) -> None:
        self.deleted = True

    def permissions_for(self, member):
        return SimpleNamespace()


class FakeGuild:
    def __init__(self) -> None:
        self.id = 123
        self.owner_id = 1
        self.default_role = FakeIdentity(0)
        self.me = FakeIdentity(999)
        self.resources: dict[int, object] = {}
        self.roles = {700: FakeIdentity(700)}
        self.member = FakeIdentity(100)
        self.created_categories = 0
        self.created_text_channels = 0
        self._next = 1000

    @property
    def channels(self) -> list[object]:
        return [
            item
            for item in self.resources.values()
            if isinstance(item, (FakeCategory, FakeTextChannel))
        ]

    @property
    def categories(self) -> list[FakeCategory]:
        return [
            item for item in self.resources.values() if isinstance(item, FakeCategory)
        ]

    def next_id(self) -> int:
        self._next += 1
        return self._next

    def get_channel(self, resource_id: int):
        item = self.resources.get(resource_id)
        return item if not isinstance(item, FakeThread) else None

    def get_thread(self, resource_id: int):
        item = self.resources.get(resource_id)
        return item if isinstance(item, FakeThread) else None

    async def fetch_channel(self, resource_id: int):
        return self.resources[resource_id]

    def get_role(self, role_id: int):
        return self.roles.get(role_id)

    def get_member(self, member_id: int):
        return self.member if member_id == self.member.id else None

    async def fetch_member(self, member_id: int):
        return self.get_member(member_id)

    async def create_category(self, name: str, **kwargs) -> FakeCategory:
        self.created_categories += 1
        category = FakeCategory(self.next_id(), name)
        self.resources[category.id] = category
        return category

    async def create_text_channel(
        self, name: str, *, category: FakeCategory | None = None, **kwargs
    ) -> FakeTextChannel:
        self.created_text_channels += 1
        channel = FakeTextChannel(self.next_id(), name, self, category)
        self.resources[channel.id] = channel
        return channel


class FakePlatformAPI:
    def __init__(self) -> None:
        self.config = {
            "version": 4,
            "data": {
                "category_id": "10",
                "panel_channel_id": "11",
                "log_channel_id": "12",
                "administrator_role_ids": ["700"],
            },
        }

    async def effective_configuration(self, guild_id: int, module_key: str) -> dict:
        assert guild_id == 123 and module_key == "farm_tickets"
        return self.config


class FakeTicketsAPI:
    def __init__(self, ticket: dict) -> None:
        self.ticket_data = ticket
        self.rows: list[dict] = []
        self.errors: list[str | None] = []
        self._next = 1

    async def ticket(self, guild_id: int, ticket_id: str) -> dict:
        assert guild_id == 123 and ticket_id == self.ticket_data["id"]
        return self.ticket_data

    async def bindings(
        self, guild_id: int, *, ticket_id: str | None = None
    ) -> list[dict]:
        return [
            item
            for item in self.rows
            if ticket_id is None or item.get("ticket_id") == ticket_id
        ]

    async def upsert_binding(
        self, guild_id: int, payload: dict, *, actor: dict
    ) -> dict:
        ticket_id = payload.get("ticket_id")
        existing = next(
            (
                item
                for item in self.rows
                if item.get("ticket_id") == ticket_id
                and item["kind"] == payload["kind"]
                and (
                    payload["kind"] != "CATEGORY"
                    or item["resource_id"] == payload["resource_id"]
                    or item["state"] == "MISSING"
                )
            ),
            None,
        )
        if existing is None:
            existing = {
                "id": f"binding-{self._next}",
                "ticket_id": ticket_id,
                "state": "ACTIVE",
            }
            self._next += 1
            self.rows.append(existing)
        existing.update(payload)
        existing["state"] = "ACTIVE"
        return existing

    async def resource_deleted(self, guild_id, resource_id, observed_at, *, actor):
        for item in self.rows:
            if item["resource_id"] == str(resource_id):
                item["state"] = "MISSING"
        return {"known": True, "action": "recover"}

    async def provisioning_error(self, guild_id, ticket_id, *, actor, error):
        self.errors.append(error)
        return self.ticket_data

    async def cleanup_state(self, guild_id, ticket_id):
        return {"ready": True}

    async def binding_deleted(self, guild_id, binding_id, *, actor, idempotency_key):
        row = next(item for item in self.rows if item["id"] == binding_id)
        row["state"] = "DELETED"
        return row


class FakePublisher:
    messages: dict[tuple[str, str], int] = {}

    def __init__(self, bot, platform_api) -> None:
        pass

    async def reconcile(self, **kwargs) -> dict:
        key = (kwargs["panel_key"], kwargs["resource_id"])
        self.messages.setdefault(key, 2000 + len(self.messages))
        return {"message_id": str(self.messages[key])}


def _actor() -> ActorContext:
    return ActorContext(
        guild_id=123,
        user_id=999,
        role_ids=(),
        discord_permissions=(),
        channel_id=None,
        category_id=None,
        actor_type="system",
        is_guild_owner=False,
        correlation_id="runtime-acceptance",
    )


def _ticket() -> dict:
    return {
        "id": "ticket-a",
        "member_id": "100",
        "member_name": "Ana",
        "player_id": "10",
        "status": "IN_PROGRESS",
        "progress_percent": "50.00",
        "assigned_admin_id": None,
        "binding_released": False,
        "objectives": [
            {
                "name": "Ferro",
                "target": "100.000",
                "launched": "50.000",
                "withdrawn": "20.000",
                "available": "30.000",
            }
        ],
    }


def test_runtime_recovers_category_panel_log_ticket_channel_and_thread_idempotently(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        guild = FakeGuild()
        platform_api = FakePlatformAPI()
        tickets_api = FakeTicketsAPI(_ticket())
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        monkeypatch.setattr(runtime.discord, "CategoryChannel", FakeCategory)
        monkeypatch.setattr(runtime.discord, "TextChannel", FakeTextChannel)
        monkeypatch.setattr(runtime.discord, "Thread", FakeThread)
        monkeypatch.setattr(runtime, "FarmTicketsAPI", lambda api: tickets_api)
        monkeypatch.setattr(runtime, "PanelPublisher", FakePublisher)

        first = await runtime._provision_ticket(
            bot, platform_api, guild, "ticket-a", _actor()
        )
        created = (guild.created_categories, guild.created_text_channels)
        # Simula crash depois de criar a thread e antes de persistir o binding.
        tickets_api.rows = [
            item for item in tickets_api.rows if item["kind"] != "TICKET_THREAD"
        ]
        second = await runtime._provision_ticket(
            bot, platform_api, guild, "ticket-a", _actor()
        )

        assert created == (1, 3)  # categoria, painel, log e canal privado
        assert (guild.created_categories, guild.created_text_channels) == created
        assert first == second
        assert {item["kind"] for item in tickets_api.rows} >= {
            "CATEGORY",
            "GLOBAL_PANEL_CHANNEL",
            "GLOBAL_PANEL_MESSAGE",
            "LOG_CHANNEL",
            "TICKET_CHANNEL",
            "TICKET_PANEL_MESSAGE",
            "TICKET_MAIN_MESSAGE",
            "TICKET_THREAD",
        }
        assert all(error is None for error in tickets_api.errors)
        ticket_channel = guild.get_channel(int(first["channel_id"]))
        assert len(ticket_channel.edits) == 2
        log_channel = next(
            item
            for item in guild.channels
            if isinstance(item, FakeTextChannel) and item.name == "logs-ticket-farm"
        )
        assert len(log_channel.messages) == 1
        main_message = next(iter(log_channel.messages.values()))
        assert main_message.thread_creations == 1

    asyncio.run(scenario())


def test_runtime_creates_numbered_category_only_after_real_fifty_channel_limit(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        guild = FakeGuild()
        primary = await guild.create_category("TICKETS DE FARM")
        for index in range(runtime.MAX_CATEGORY_CHANNELS):
            await guild.create_text_channel(f"ticket-{index}", category=primary)
        api = FakeTicketsAPI(_ticket())
        monkeypatch.setattr(runtime.discord, "CategoryChannel", FakeCategory)
        selected = await runtime._select_ticket_category(guild, api, _actor(), primary)
        assert selected.name == "TICKETS DE FARM 2"
        assert len(primary.channels) == 50
        assert selected.channels == []

    asyncio.run(scenario())


def test_runtime_reparents_adopted_channels_when_category_is_recovered(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        guild = FakeGuild()
        platform_api = FakePlatformAPI()
        api = FakeTicketsAPI(_ticket())
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        monkeypatch.setattr(runtime.discord, "CategoryChannel", FakeCategory)
        monkeypatch.setattr(runtime.discord, "TextChannel", FakeTextChannel)
        monkeypatch.setattr(runtime, "FarmTicketsAPI", lambda platform: api)
        monkeypatch.setattr(runtime, "PanelPublisher", FakePublisher)

        original, panel, log = await runtime._ensure_global_resources(
            bot, platform_api, guild, _actor()
        )
        guild.resources.pop(original.id)
        for binding in api.rows:
            if binding["kind"] == "CATEGORY":
                binding["state"] = "MISSING"

        recovered, same_panel, same_log = await runtime._ensure_global_resources(
            bot, platform_api, guild, _actor()
        )

        assert recovered.id != original.id
        assert same_panel is panel
        assert same_log is log
        assert panel.category_id == recovered.id
        assert log.category_id == recovered.id
        assert panel.edits[-1]["category"] is recovered
        assert log.edits[-1]["category"] is recovered

    asyncio.run(scenario())


def test_raw_thread_delete_is_dispatched_to_module_recovery() -> None:
    class Bot:
        def __init__(self) -> None:
            self.deleted: list[tuple[int, int]] = []

        async def _dispatch_resource_delete(
            self, guild_id: int, resource_id: int
        ) -> None:
            self.deleted.append((guild_id, resource_id))

    async def scenario() -> None:
        bot = Bot()
        payload = SimpleNamespace(guild_id=123, thread_id=456)

        await bot_main.YunoBot.on_raw_thread_delete(bot, payload)

        assert bot.deleted == [(123, 456)]

    asyncio.run(scenario())


def test_terminal_cleanup_deletes_panel_message_before_ticket_channel(
    monkeypatch,
) -> None:
    async def scenario() -> None:
        ticket = {**_ticket(), "binding_released": True}
        guild = FakeGuild()
        channel = await guild.create_text_channel("ticket-10-ana")
        message = await channel.send(content="painel")
        api = FakeTicketsAPI(ticket)
        api.rows = [
            {
                "id": "binding-panel",
                "ticket_id": ticket["id"],
                "kind": "TICKET_PANEL_MESSAGE",
                "resource_id": str(message.id),
                "parent_resource_id": str(channel.id),
                "ownership": "MANAGED",
                "state": "DELETE_PENDING",
            },
            {
                "id": "binding-channel",
                "ticket_id": ticket["id"],
                "kind": "TICKET_CHANNEL",
                "resource_id": str(channel.id),
                "parent_resource_id": None,
                "ownership": "MANAGED",
                "state": "DELETE_PENDING",
            },
        ]
        bot = SimpleNamespace(user=SimpleNamespace(id=999))
        monkeypatch.setattr(runtime.discord, "TextChannel", FakeTextChannel)
        monkeypatch.setattr(runtime.discord, "Thread", FakeThread)
        monkeypatch.setattr(runtime, "FarmTicketsAPI", lambda platform_api: api)

        result = await runtime._cleanup_ticket_resources(
            bot, FakePlatformAPI(), guild, ticket["id"], _actor()
        )

        assert result["deleted_bindings"] == 2
        assert message.deleted
        assert channel.deleted
        assert all(item["state"] == "DELETED" for item in api.rows)

    asyncio.run(scenario())
