from functools import lru_cache
from logging import getLogger
from typing import Optional

from canvasapi import Canvas
from canvasapi.account import Account
from canvasapi.calendar_event import CalendarEvent
from canvasapi.course import Course
from canvasapi.discussion_topic import DiscussionTopic
from canvasapi.exceptions import CanvasException
from canvasapi.paginated_list import PaginatedList
from canvasapi.user import User as CanvasUser

from config.config import DEBUG_VALUE, PROD_KEY, PROD_URL, TEST_KEY, TEST_URL
from form.terms import CURRENT_TERM, NEXT_TERM

logger = getLogger(__name__)
MAIN_ACCOUNT_ID = 96678


def get_canvas() -> Canvas:
    url = TEST_URL if DEBUG_VALUE else PROD_URL
    key = TEST_KEY if DEBUG_VALUE else PROD_KEY
    return Canvas(url, key)


def get_base_url() -> str:
    return TEST_URL if DEBUG_VALUE else PROD_URL


def get_canvas_account(account_id: int) -> Account:
    return get_canvas().get_account(account_id)


def get_canvas_main_account() -> Account:
    return get_canvas_account(MAIN_ACCOUNT_ID)


@lru_cache
def get_all_canvas_accounts() -> list[Account]:
    return list(get_canvas_main_account().get_subaccounts(recursive=True))


def get_canvas_user_by_pennkey(pennkey: str) -> Optional[CanvasUser]:
    try:
        return get_canvas().get_user(pennkey, "sis_login_id")
    except CanvasException:
        return None


def get_canvas_user_id_by_pennkey(pennkey: str) -> Optional[int]:
    user = get_canvas_user_by_pennkey(pennkey)
    return user.id if user else None


def get_canvas_enrollment_term_id(term: int) -> Optional[int]:
    term_name = str(term)
    account = get_canvas_main_account()
    enrollment_terms = account.get_enrollment_terms()
    enrollment_term_ids = (
        term.id for term in enrollment_terms if term_name in term.name
    )
    return next(enrollment_term_ids, None)


def get_canvas_enrollment_term_name(enrollment_term_id: int) -> str:
    account = get_canvas_main_account()
    try:
        return account.get_enrollment_term(enrollment_term_id).name
    except Exception:
        return ""


def get_current_term() -> str:
    current_term_id = get_canvas_enrollment_term_id(CURRENT_TERM)
    if current_term_id:
        return get_canvas_enrollment_term_name(current_term_id)
    else:
        return str(CURRENT_TERM)


def get_next_term() -> str:
    next_term_id = get_canvas_enrollment_term_id(NEXT_TERM)
    if next_term_id:
        return get_canvas_enrollment_term_name(next_term_id)
    else:
        return str(NEXT_TERM)


def create_course_section(name: str, sis_course_id: str, canvas_course: Course):
    course_section = {"name": name, "sis_section_id": sis_course_id}
    canvas_course.create_course_section(
        course_section=course_section, enable_sis_reactivation=True
    )


def update_canvas_course(course: dict) -> tuple[Optional[Course], Optional[Exception]]:
    sis_course_id = course["sis_course_id"]
    error_message = None
    try:
        canvas_course = get_canvas().get_course(sis_course_id, use_sis_id=True)
        canvas_course.update(course=course)
        return canvas_course, error_message
    except Exception as error:
        error_message = error
        logger.error(
            f"FAILED to update Canvas course '{sis_course_id}': {error_message}"
        )
        return None, error_message


def update_or_create_canvas_course(
    course: dict, account_id: int
) -> tuple[bool, Optional[Course], Optional[Exception]]:
    created = True
    error_message = None
    try:
        account = get_canvas_account(account_id)
        canvas_course = account.create_course(course=course)
        name = canvas_course.name
        sis_course_id = canvas_course.sis_course_id
        create_course_section(name, sis_course_id, canvas_course)
        return created, canvas_course, error_message
    except Exception:
        created = False
        canvas_course, error_message = update_canvas_course(course)
        return created, canvas_course, error_message


def get_calendar_events(course_id: int) -> PaginatedList:
    context_codes = [f"course_{course_id}"]
    canvas = get_canvas()
    return canvas.get_calendar_events(context_codes=context_codes, all_events=True)


def contains_zoom(event_property: Optional[str]) -> bool:
    return bool(event_property and "zoom" in event_property.lower())


def is_zoom_event(event: CalendarEvent) -> bool:
    return (
        contains_zoom(event.location_name)
        or contains_zoom(event.description)
        or contains_zoom(event.title)
    )


def delete_zoom_event(event_id: int):
    event = get_canvas().get_calendar_event(event_id)
    cancel_reason = "Content migration"
    deleted = event.delete(cancel_reason=cancel_reason)
    deleted = deleted.title.encode("ascii", "ignore")
    logger.info(f"DELETED event '{deleted}'")


def delete_announcement(announcement: DiscussionTopic):
    announcement.delete()
    logger.info(f"DELETED announcement '{announcement.title}'")


def delete_zoom_events(canvas_course):
    logger.info("Deleting Zoom events...")
    events = get_calendar_events(canvas_course.id)
    zoom_events = [event.id for event in events if is_zoom_event(event)]
    for event_id in zoom_events:
        delete_zoom_event(event_id)


def delete_announcements(canvas_course):
    logger.info("Deleting Announcements...")
    announcements = canvas_course.get_discussion_topics(only_announcements=True)
    announcements = [announcement for announcement in announcements]
    for announcement in announcements:
        delete_announcement(announcement)


def get_user_canvas_sites(username: str) -> Optional[list[Course]]:
    user = get_canvas_user_by_pennkey(username)
    if not user:
        return None
    return list(user.get_courses(enrollment_type="teacher"))
