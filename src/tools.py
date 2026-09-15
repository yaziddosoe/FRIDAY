import asyncio
import logging
from datetime import datetime

from livekit.agents import RunContext, function_tool

import weather
from memory import MemoryStore


@function_tool
async def search_web(context: RunContext, query: str):
    """
    use this tool to search the web for information related to the given query.
    """

    try:
        result = await asyncio.to_thread(_ddgs_search, query)
    except Exception:
        logging.exception("DDGS web search failed for query '%s'", query)
        return (
            "My web search hit a snag, sir. Try asking again in a slightly "
            "different way."
        )
    if not result:
        return "I could not find anything for that query. Try rephrasing it, sir."
    return result


def _ddgs_search(query: str, *, max_results: int = 4, timeout: float = 12.0) -> str:
    from ddgs import DDGS
    from ddgs.ddgs import DDGSException

    try:
        results = DDGS(timeout=timeout).text(
            query,
            max_results=max_results,
            safesearch="moderate",
            backend="auto",
        )
    except DDGSException:
        return ""
    lines: list[str] = []
    for item in results or []:
        title = (item.get("title") or "").strip()
        body = (item.get("body") or "").strip()
        if title and body:
            lines.append(f"- {title}: {body}")
        elif title:
            lines.append(f"- {title}")
    text = "\n".join(lines).strip()
    if len(text) > 1500:
        text = text[:1497] + "..."
    return text


@function_tool
async def get_weather(context: RunContext, place: str = ""):
    """Gets the current weather and today's high/low for any city or place.

    Use this whenever the user asks about the weather, temperature, rain,
    or the forecast. If no place is given it uses the user's default city.

    Args:
        place: The city or place to check, e.g. "Paramaribo". Leave empty for the user's default city.
    """

    try:
        return await asyncio.to_thread(weather.fetch_weather, place)
    except weather.WeatherError as exc:
        logging.info("Weather request failed: %s", exc)
        return str(exc)
    except Exception:
        logging.exception("Unexpected weather lookup failure")
        return "I could not fetch the weather right now, sir. Please try again shortly."


@function_tool
async def get_current_datetime(context: RunContext):
    """Returns the current local date and time, including the weekday, in the user's timezone.

    Use this tool whenever the user asks for the time, date, or day of the week.
    """

    now = datetime.now().astimezone()
    return now.strftime("%A, %B %d, %Y at %I:%M %p (%Z, UTC offset %z)")


@function_tool
async def remember_fact(context: RunContext, fact: str):
    """Stores a fact about the user so FRIDAY remembers it in future conversations.

    Use this when the user tells you a preference, name, or any other information
    they want you to remember long-term.

    Args:
        fact: A complete sentence describing the fact to remember (e.g. "The user prefers coffee over tea").
    """

    return await asyncio.to_thread(_remember_fact, fact)


def _remember_fact(fact: str) -> str:
    store = MemoryStore()
    store.add_fact(fact)
    logging.info("Stored memory fact: %s", fact)
    return f"Remembered: {fact}"


@function_tool
async def forget_fact(context: RunContext, keyword: str):
    """Forgets stored facts about the user that match the given keyword.

    Use this when the user asks you to stop remembering something.

    Args:
        keyword: A word or phrase that appears in the fact(s) to forget.
    """

    return await asyncio.to_thread(_forget_fact, keyword)


def _forget_fact(keyword: str) -> str:
    store = MemoryStore()
    removed = store.forget_fact(keyword)
    logging.info("Forgot %d fact(s) matching '%s'", removed, keyword)
    if removed == 0:
        return "I could not find any stored facts matching that."
    return f"Forgot {removed} matching fact(s)."
