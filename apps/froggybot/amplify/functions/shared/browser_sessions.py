"""Direct-chat browser handoff with private profiles and fail-closed transitions.

Runtime consumers must pass their existing table/client. No clients are created
at import time. Login is not approval to submit forms or perform external writes.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from datetime import datetime, timezone

from .browser_display import (
    VIEWPORTS,
    extension_configuration,
    open_options,
    prepare_browser,
)
from .browser_session_aws import (
    BROWSER_IDENTIFIER,
    SESSION_SECONDS,
    VIEW_SECONDS,
    automation,
    live_view_url,
    session_args,
    session_ended,
    stop_session,
)
from .browser_session_store import BrowserSessionError, BrowserSessionStore, direct_only
from .memory_identity import memory_actor_id

OPERATION_SECONDS = 45
RESUME_PROMPT = (
    "I have finished interacting with your browser. Continue ONLY the most recent "
    "user request immediately before this browser handoff, not an older task "
    "recalled from memory. Preserve that request's limits, including read-only "
    "or test-only restrictions. If it is already complete, inspect the current "
    "page and report that there is no unfinished work; do not revive older tasks. "
    "Use this bot's managed browser session. Verify the current page and login "
    "state, and verify completed external actions before repeating anything. "
    "Browser authentication is not new authorization to submit forms, post, merge, "
    "purchase, or perform other external actions. Keep existing tool-approval "
    "requirements and ask for any missing authorization."
)


def managed_session_name(user_id: str, bot_id: str) -> str:
    digest = hashlib.sha256(f"{memory_actor_id(user_id)}:bot:{bot_id}".encode()).hexdigest()
    return f"frogbot-browser-{digest[:48]}"


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


class BrowserSessionService:
    def __init__(self, table, agentcore, user_id, bot_id, group_id=None, *,
                 control=None, catalog=None, signer=live_view_url, clock=time.time):
        direct_only(group_id)
        self.store = BrowserSessionStore(table, user_id, bot_id, catalog)
        self.agentcore = agentcore
        self.control = control
        self.signer = signer
        self.clock = clock
        self.name = managed_session_name(user_id, bot_id)

    def _now(self):
        return int(self.clock())

    def _view(self, record: dict, bot: dict) -> dict:
        status = record["status"]
        if record.get("resumeState") in {"ENQUEUEING", "UNCERTAIN"}:
            status = "RESUMING"
        if (status in {"READY", "HUMAN_CONTROL"} and
                int(record.get("sessionExpiresAt", 0)) <= self._now()):
            status = "EXPIRED"
        result = {"status": status.lower(), "botId": self.store.bot_id,
                  "contextLabel": f"{bot.get('name', 'Bot')} · Private direct chat",
                  "hasSavedLogin": bool(record.get("profileId") and record.get("profileVersion"))}
        display = record.get("display", "desktop")
        # The DCV desktop size belongs to the session, not the site preference.
        # Existing sessions cannot assume AWS's optional resize channel works.
        viewport = record.get("viewport") or VIEWPORTS["desktop"]
        result.update(display=display, viewport={key: int(viewport[key]) for key in ("width", "height")},
                      mobileSiteSupported=bool(record.get("mobileExtension")))
        if record.get("sessionExpiresAt"):
            result["sessionExpiresAt"] = _iso(int(record["sessionExpiresAt"]))
        if record.get("resumedTurnId"):
            result["resumedTurnId"] = record["resumedTurnId"]
        return result

    def _valid(self, record: dict) -> bool:
        if not record.get("sessionId") or int(record.get("sessionExpiresAt", 0)) <= self._now():
            return False
        try:
            session = self.agentcore.get_browser_session(**session_args(record))
        except self.agentcore.exceptions.ResourceNotFoundException:
            return False
        if session.get("name") != self.name:
            raise BrowserSessionError(403, "Browser session does not belong to this context")
        return session.get("status") == "READY"

    def _claim(self, record: dict, status: str, operation: str, **changes) -> dict:
        if record.get("revoked") and operation not in {"close", "forget"}:
            raise BrowserSessionError(409, "This browser connection is being deleted")
        if int(record.get("operationUntil", 0)) > self._now():
            raise BrowserSessionError(409, "A browser operation is still in progress")
        return self.store.write(record, status=status, operation=operation,
                                operationId=str(uuid.uuid4()),
                                operationUntil=self._now() + OPERATION_SECONDS,
                                lastError=None, **changes)

    def _failed(self, record: dict, code: str) -> None:
        # Only a static failure code is stored. SDK errors may contain secret data.
        self.store.write(record, lastError=code, lastFailureCode=code,
                         lastFailureAt=self._now(), operationUntil=0)

    def _start(self, record: dict) -> dict:
        # Persist the token BEFORE Start so cleanup can recover an uncertain result.
        if not record.get("startToken"):
            record = self.store.write(record, startToken=str(uuid.uuid4()))
        request = {"browserIdentifier": BROWSER_IDENTIFIER, "name": self.name,
                   "sessionTimeoutSeconds": SESSION_SECONDS,
                   "clientToken": record["startToken"],
                   "viewPort": VIEWPORTS[record.get("display", "desktop")]}
        extensions = extension_configuration()
        if extensions:
            request["extensions"] = extensions
        if record.get("profileId") and record.get("profileVersion"):
            request["profileConfiguration"] = {"profileIdentifier": record["profileId"]}
        try:
            result = self.agentcore.start_browser_session(**request)
        except Exception as exc:
            self._failed(record, "SESSION_START_UNCERTAIN")
            raise BrowserSessionError(503, "Browser start could not be confirmed. Close the browser before retrying") from exc
        created = result.get("createdAt")
        started = int(created.timestamp()) if isinstance(created, datetime) else self._now()
        return self.store.write(record, sessionId=result["sessionId"], sessionName=self.name,
                                mobileExtension=bool(extensions),
                                viewport=request["viewPort"],
                                sessionExpiresAt=min(started, self._now()) + SESSION_SECONDS)

    def get(self) -> dict:
        bot = self.store.authorize()
        record = self.store.read()
        if self._ended_handoff(record):
            record = {**record, "status": "EXPIRED", "resumedTurnId": None}
        if record["status"] in {"READY", "HUMAN_CONTROL"} and not self._valid(record):
            record = {**record, "status": "EXPIRED"}
        view = self._view(record, bot)
        if record["status"] in {"OPENING", "RESUMING"}:
            view["recoveryRequired"] = int(record.get("operationUntil", 0)) <= self._now()
        return view

    def _ended_handoff(self, record: dict) -> bool:
        # Only recover an abandoned open/close with affirmative AWS evidence.
        # Never interrupt a live operation, profile save, or uncertain enqueue.
        if (record.get("revoked") or int(record.get("operationUntil", 0)) > self._now()
                or record.get("resumeState") in {"WAIT_PROFILE", "ENQUEUEING", "UNCERTAIN"}):
            return False
        abandoned = record["status"] == "OPENING" or (
            record["status"] == "RESUMING" and record.get("operation") == "close")
        return abandoned and session_ended(self.agentcore, record, self.name)

    def open(self, display=None, url=None) -> dict:
        """API must hold the direct-chat send lease through this whole method."""
        display, url = open_options({"display": display, "url": url})
        bot = self.store.authorize()
        self.store.ensure_idle()
        record = self.store.read()
        if self._ended_handoff(record):
            record = {**record, "status": "EXPIRED"}
        if record["status"] in {"OPENING", "RESUMING"} or record.get("resumeState") in {"ENQUEUEING", "UNCERTAIN"}:
            raise BrowserSessionError(409, "Finish or close the previous browser handoff first")
        record = self._claim(record, "OPENING", "open", display=display or record.get("display", "desktop"),
                             resumeState=None, resumedTurnId=None)
        try:
            if not self._valid(record):
                stop_session(self.agentcore, record)
                record = self.store.write(record, sessionId=None, startToken=None)
                record = self._start(record)
            if display or url:
                # No worker can run while the send lease / OPENING state is held.
                # Configure only before issuing a human viewer capability, then
                # always disable automation, even on failed setup/navigation.
                try:
                    automation(self.agentcore, record, True)
                    prepare_browser(self.agentcore, record, record["display"], url)
                finally:
                    automation(self.agentcore, record, False)
            else:
                automation(self.agentcore, record, False)
            # Sign only after AWS has disabled automation, never on GET or resume.
            url = self.signer(self.agentcore, record["sessionId"])
            record = self.store.write(record, status="HUMAN_CONTROL", operationUntil=0,
                                      resumeState=None, resumedTurnId=None)
        except BrowserSessionError:
            raise
        except Exception as exc:
            self._failed(record, "OPEN_FAILED")
            raise BrowserSessionError(503, "Could not open the browser. Close it before retrying") from exc
        return {**self._view(record, bot), "liveViewUrl": url,
                "liveViewExpiresAt": _iso(min(self._now() + VIEW_SECONDS, int(record["sessionExpiresAt"])))}

    def _save_profile(self, record: dict) -> dict:
        if not record.get("profileId"):
            if not record.get("profileCreateToken"):
                record = self.store.write(record, profileCreateToken=str(uuid.uuid4()))
            # A fresh name after explicit forgetting; repeated creates use one token.
            suffix = hashlib.sha256(record["profileCreateToken"].encode()).hexdigest()[:40]
            result = self.control.create_browser_profile(
                name=f"frogbot_{suffix}", clientToken=record["profileCreateToken"],
                tags={"frogbot:managed-by": "FrogBot"},
            )
            record = self.store.write(record, profileId=result["profileId"])
        if record.get("resumeState") != "WAIT_PROFILE":
            if not record.get("profileSaveToken"):
                record = self.store.write(record, profileSaveToken=str(uuid.uuid4()))
            self.agentcore.save_browser_session_profile(
                **session_args(record), profileIdentifier=record["profileId"],
                clientToken=record["profileSaveToken"],
            )
            record = self.store.write(record, resumeState="WAIT_PROFILE")
        profile = self.control.get_browser_profile(profileId=record["profileId"])
        if profile.get("status") == "SAVING" or (
            profile.get("status") == "READY"
            and profile.get("lastSavedBrowserSessionId") != record["sessionId"]
        ):
            return self.store.write(record, operationUntil=0)
        if profile.get("status") != "READY":
            raise BrowserSessionError(409, "The saved browser profile is not ready")
        return self.store.write(record, resumeState="PROFILE_SAVED",
                                profileVersion=int(record.get("profileVersion", 0)) + 1)

    def resume(self, remember_login: bool, enqueue) -> dict:
        if not isinstance(remember_login, bool):
            raise BrowserSessionError(400, "rememberLogin must be a boolean")
        bot = self.store.authorize()
        record = self.store.read()
        if record.get("resumedTurnId") and record.get("resumeState") == "COMPLETE":
            return self._view(record, bot)
        waiting = record["status"] == "RESUMING" and record.get("resumeState") == "WAIT_PROFILE"
        if record["status"] != "HUMAN_CONTROL" and not waiting:
            raise BrowserSessionError(409, "Open the browser before resuming; an uncertain handoff cannot be repeated")
        if waiting and record.get("rememberLogin") != remember_login:
            raise BrowserSessionError(409, "A profile save is already in progress")
        self.store.ensure_idle()
        if not self._valid(record):
            raise BrowserSessionError(409, "The browser session expired. Open it again before resuming")
        record = self._claim(record, "RESUMING", "resume", rememberLogin=remember_login)
        try:
            if remember_login:
                record = self._save_profile(record)
                if record.get("resumeState") == "WAIT_PROFILE":
                    return self._view(record, bot)
            automation(self.agentcore, record, True)
            # READY before enqueue lets the worker attach; this marker prevents
            # another open/resume/close from racing the single enqueue attempt.
            record = self.store.write(record, status="READY", resumeState="ENQUEUEING")
            result = enqueue(RESUME_PROMPT)
            turn_id = result.get("turnId")
            if not isinstance(turn_id, str) or not turn_id:
                raise ValueError("Continuation did not return a turn identifier")
            record = self.store.write(record, resumedTurnId=turn_id, resumeState="COMPLETE",
                                      operationUntil=0, profileSaveToken=None)
        except Exception as exc:
            # Do not re-enqueue even when the queue call failed: acceptance may
            # have happened before its response was lost. Close is explicit recovery.
            latest = self.store.read()
            if latest.get("operationId") == record.get("operationId"):
                self.store.write(latest, resumeState="UNCERTAIN", lastError="RESUME_UNCERTAIN",
                                 lastFailureCode="RESUME_UNCERTAIN", lastFailureAt=self._now(),
                                 operationUntil=0)
            raise BrowserSessionError(503, "Resume could not be confirmed. Check the conversation before closing or retrying; no automatic retry was sent") from exc
        return self._view(record, bot)

    def close(self, *, forget: bool = False) -> dict:
        bot = self.store.authorize(require_browser=False)
        return self._disconnect(bot, forget=forget)

    def _disconnect(self, bot: dict, *, forget: bool) -> dict:
        record = self._claim(self.store.read(), "RESUMING", "forget" if forget else "close")
        try:
            # If Start timed out after acceptance, the same token recovers ONLY
            # that session so it can be terminated. Never list another user's sessions.
            if record.get("startToken") and not record.get("sessionId"):
                record = self._start(record)
            stop_session(self.agentcore, record)
            if forget:
                if record.get("profileCreateToken") and not record.get("profileId"):
                    suffix = hashlib.sha256(record["profileCreateToken"].encode()).hexdigest()[:40]
                    result = self.control.create_browser_profile(
                        name=f"frogbot_{suffix}", clientToken=record["profileCreateToken"],
                        tags={"frogbot:managed-by": "FrogBot"},
                    )
                    record = self.store.write(record, profileId=result["profileId"])
                if record.get("profileId"):
                    try:
                        self.control.delete_browser_profile(profileId=record["profileId"])
                    except self.control.exceptions.ResourceNotFoundException:
                        pass
                record = self.store.write(record, profileId=None, profileVersion=0,
                                          profileCreateToken=None, profileSaveToken=None)
            record = self.store.write(record, status="CLOSED", operationUntil=0,
                                      sessionId=None, sessionExpiresAt=None, startToken=None,
                                      resumeState=None, resumedTurnId=None, profileSaveToken=None)
        except Exception as exc:
            latest = self.store.read()
            if latest.get("operationId") == record.get("operationId"):
                self._failed(latest, "CLOSE_FAILED")
            raise BrowserSessionError(503, "Browser disconnect is incomplete; retry Close or Forget") from exc
        return self._view(record, bot)

    def runtime_session(self) -> dict | None:
        record = self.store.read()
        if not record["revision"]:
            return None
        self.store.authorize()
        if record.get("revoked"):
            raise BrowserSessionError(409, "Browser connection has been revoked")
        if record["status"] in {"HUMAN_CONTROL", "OPENING", "RESUMING"} or record.get("resumeState") == "UNCERTAIN":
            raise BrowserSessionError(409, "Browser is under human control or awaiting handoff; do not use a fallback browser")
        if not self._valid(record):
            if not record.get("profileId") or not record.get("profileVersion"):
                return None
            record = self._claim(record, "OPENING", "restore")
            try:
                stop_session(self.agentcore, record)
                record = self.store.write(record, sessionId=None, startToken=None)
                record = self._start(record)
                record = self.store.write(record, status="READY", operationUntil=0)
            except BrowserSessionError:
                raise
            except Exception as exc:
                latest = self.store.read()
                if latest.get("operationId") == record.get("operationId"):
                    self._failed(latest, "RESTORE_FAILED")
                raise BrowserSessionError(503, "Saved browser could not be restored") from exc
        return {"browserIdentifier": BROWSER_IDENTIFIER, "sessionId": record["sessionId"],
                "sessionName": self.name}


def runtime_browser_session(table, agentcore, user_id: str, bot_id: str,
                            group_id: str | None = None) -> dict | None:
    """Return only a private direct session binding; group calls NEVER inherit it.

    Raises BrowserSessionError on human control/uncertain handoff. The caller must
    fail closed, not catch this to select the legacy browser. No profile control
    permissions or signed URLs are needed by the worker/runtime.
    """
    if group_id is not None:
        return None
    return BrowserSessionService(table, agentcore, user_id, bot_id).runtime_session()


def ensure_browser_send_allowed(table, user_id: str, bot_id: str) -> None:
    """Cheap direct-send preflight; no AWS browser calls or approval changes.

    READY/ENQUEUEING must be allowed for resume's existing _send_message call.
    The worker independently verifies the binding before using it.
    """
    record = BrowserSessionStore(table, user_id, bot_id).read()
    if (record.get("revoked") or record["status"] in {"HUMAN_CONTROL", "OPENING", "RESUMING"}
            or record.get("resumeState") == "UNCERTAIN"):
        raise BrowserSessionError(409, "Finish the browser handoff with Resume or Close before sending another message")


def delete_browser_context(table, user_id: str, bot_id: str, *, agentcore=None,
                           control=None) -> None:
    """Cleanup-only: identity comes from an authorized bot/account deletion path.

    Does not require the bot or its browser capability to still exist. Do not
    expose this function as an unauthenticated route. Keep references on failure.
    """
    store = BrowserSessionStore(table, user_id, bot_id)
    record = store.read()
    if not record["revision"]:
        return
    if agentcore is None or control is None:
        from .browser_session_aws import browser_clients

        data_client, control_client = browser_clients()
        agentcore = agentcore or data_client
        control = control or control_client
    service = BrowserSessionService(table, agentcore, user_id, bot_id, control=control)
    if not record.get("revoked"):
        store.write(record, revoked=True)
    service._disconnect({"name": "Deleted bot"}, forget=True)
    # Keep a closed tombstone until the caller deletes its parent bot/account.
    # Deleting this item now would create an ABA race with an in-flight opener.
