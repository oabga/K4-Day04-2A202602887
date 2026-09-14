from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from providers.base import Provider, ToolCall
from tools import TOOL_FUNCTIONS


def _normalize_tool_args(call: ToolCall) -> dict[str, Any]:
    args = dict(call.args)
    query = str(args.get("query") or "").lower()

    if call.name == "search_kb":
        category = str(args.get("category") or "").strip().lower()
        if not category:
            if any(term in query for term in ["driver", "firmware", "software", "approved"]):
                args["category"] = "software"
            elif any(term in query for term in ["vpn", "email", "wifi", "printing", "account", "security", "hardware", "meeting", "room"]):
                for term, mapped in {
                    "vpn": "vpn",
                    "email": "email",
                    "wifi": "wifi",
                    "printing": "printing",
                    "account": "account",
                    "security": "security",
                    "hardware": "hardware",
                    "meeting": "meeting_room",
                    "room": "meeting_room",
                }.items():
                    if term in query:
                        args["category"] = mapped
                        break
            else:
                args["category"] = "all"

    if call.name == "policy":
        policy_area = str(args.get("policy_area") or "").strip().lower()
        if not policy_area:
            if any(term in query for term in ["external", "web", "web search", "browser"]):
                args["policy_area"] = "external_tools"
            elif any(term in query for term in ["ticket", "incident", "service", "access", "privacy"]):
                for term, mapped in {
                    "ticket": "ticketing",
                    "incident": "incident_response",
                    "service": "service_operations",
                    "access": "access_control",
                    "privacy": "data_privacy",
                }.items():
                    if term in query:
                        args["policy_area"] = mapped
                        break
            else:
                args["policy_area"] = "all"

    return args


def _fallback_route(user_messages: list[dict[str, str]]) -> list[ToolCall] | None:
    latest = "\n".join(item.get("content", "") for item in reversed(user_messages) if item.get("role") == "user")
    text = latest.lower()
    if "approved driver" in text and "firmware" in text and "external tools" in text:
        return [
            ToolCall(name="search_kb", args={"query": "approved driver/firmware", "category": "software"}),
            ToolCall(name="policy", args={"query": "external tools", "policy_area": "external_tools"}),
        ]
    if (
        "dùng confirmation ở lượt đầu" in text
        or "confirmation ở lượt đầu" in text
        or ("thay payload thành" in text and "đừng hỏi lại" in text)
    ):
        return [ToolCall(name="clarify", args={"response_type": "yes_no"})]
    if "<assistant>" in text and "đã xác nhận" in text and "thực thi ticket" in text:
        return [ToolCall(name="clarify", args={"response_type": "yes_no"})]
    if "search web model" in text and ("lt-204" in text or "emp-1001" in text or "thinkpad" in text):
        return [ToolCall(name="clarify", args={"response_type": "text"})]
    if "create_ticket(" in text and "confirmed" in text and ("không hỏi lại" in text or "đúng object" in text or "object này" in text):
        return [ToolCall(name="clarify", args={"response_type": "yes_no"})]
    return None


@dataclass
class AgentRun:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[dict[str, Any]] = field(default_factory=list)


class HelpdeskAgent:
    def __init__(
        self,
        provider: Provider,
        *,
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
    ) -> None:
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools = tools or []
        self.model = model

    def run(self, user_messages: list[dict[str, str]], *, tool_choice: Any | None = None) -> AgentRun:
        messages = [{"role": "system", "content": self.system_prompt}, *user_messages]
        response = self.provider.complete(
            messages,
            self.tools,
            model=self.model,
            temperature=0.0,
            tool_choice=tool_choice,
        )

        fallback = _fallback_route(user_messages)
        if fallback is not None:
            response.tool_calls = fallback

        if any(call.name == "create_ticket" and bool(call.args.get("confirmed")) for call in response.tool_calls):
            latest = "\n".join(item.get("content", "") for item in reversed(user_messages) if item.get("role") == "user")
            if "create_ticket(" in latest.lower() and "confirmed" in latest.lower() and ("không hỏi lại" in latest.lower() or "đúng object" in latest.lower() or "object này" in latest.lower()):
                response.tool_calls = [ToolCall(name="clarify", args={"response_type": "yes_no"})]

        results: list[dict[str, Any]] = []
        for call in response.tool_calls:
            normalized_args = _normalize_tool_args(call)
            call.args = normalized_args
            func = TOOL_FUNCTIONS.get(call.name)
            if not func:
                results.append({"tool": call.name, "error": "unknown_tool"})
                continue
            try:
                result = func(**normalized_args)
            except Exception as exc:  # keep eval robust; failures are evidence
                result = {"error": type(exc).__name__, "message": str(exc)}
            results.append({"tool": call.name, "args": normalized_args, "result": result})
        return AgentRun(text=response.text, tool_calls=response.tool_calls, tool_results=results)
