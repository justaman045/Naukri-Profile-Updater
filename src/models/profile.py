from dataclasses import dataclass, field


@dataclass
class Profile:
    name: str = ""
    headline: str = ""
    summary: str = ""
    email: str = ""
    phone: str = ""
    profile_id: str = ""
    skills: str = ""
    position: str = ""
    city: str = ""
    experience_years: str = ""
    experience_months: str = ""
    expected_ctc: str = ""
    current_ctc: str = ""
    notice_period: str = ""
    resume_name: str = ""
    resume_format: str = ""
    resume_size_kb: str = ""
    resume_upload_date: str = ""
    resume_available: bool = False
    raw: dict = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, data, profile_id: str = "") -> "Profile":
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            data = {}
        # Full-profile shape: {"user": {...}, "profile": [...]}
        if "profile" in data and isinstance(data["profile"], (list, dict)):
            if isinstance(data["profile"], list):
                profile = data["profile"][0] if data["profile"] else {}
            else:
                profile = data["profile"]
        # Dashboard shape: {"dashBoard": {...}}
        elif "dashBoard" in data and isinstance(data["dashBoard"], dict):
            profile = data["dashBoard"]
        else:
            profile = data.get("profile", data)
        if not isinstance(profile, dict):
            profile = {}

        user = data.get("user", {}) if isinstance(data, dict) else {}
        if not isinstance(user, dict):
            user = {}

        emails = profile.get("emails") or []
        phones = profile.get("phone") or profile.get("phones") or []
        if not phones:
            mvn = profile.get("mvn")
            if mvn:
                phones = [mvn]
        email = _first_string(emails)
        if not email:
            email = (profile.get("username") or user.get("email") or
                     user.get("alternateEmail") or "") or ""

        phone = _first_string(phones)
        if not phone and user.get("mobile"):
            phone = str(user.get("mobile"))

        exp_years = profile.get("experience", {}).get("year", "") if isinstance(
            profile.get("experience"), dict) else ""
        exp_months = profile.get("experience", {}).get("month", "") if isinstance(
            profile.get("experience"), dict) else ""

        cv = profile.get("cvInfo") or {}
        if not isinstance(cv, dict):
            cv = {}

        return cls(
            name=profile.get("name", "") or "",
            headline=profile.get("resumeHeadline", "") or "",
            summary=profile.get("summary", "") or "",
            email=email,
            phone=str(phone),
            profile_id=profile.get("profileId", "") or profile_id,
            skills=profile.get("keySkills", "") or "",
            position=_nested_value(profile, "role") or "",
            city=_nested_value(profile, "city") or "",
            experience_years=str(exp_years),
            experience_months=str(exp_months),
            expected_ctc=_ctc_str(profile),
            current_ctc=_absolute_ctc_str(profile),
            notice_period=_nested_value(profile, "noticePeriod") or "",
            resume_name=cv.get("fileName", "") or "",
            resume_format=cv.get("cvFormat", "") or "",
            resume_size_kb=str(cv.get("sizeInKB") or ""),
            resume_upload_date=cv.get("uploadDate", "") or "",
            resume_available=bool(cv.get("isAvailable")),
            raw=profile,
        )


def _nested_value(profile: dict, key: str) -> str:
    v = profile.get(key)
    if isinstance(v, dict):
        return str(v.get("value", ""))
    if isinstance(v, (list, tuple)) and v:
        first = v[0]
        if isinstance(first, dict):
            return str(first.get("value", first.get("name", "")))
        return str(first)
    return str(v or "")


def _ctc_str(profile: dict) -> str:
    ctc = profile.get("expectedCtc")
    if isinstance(ctc, dict):
        lacs = _first_id_value(ctc.get("lacs"))
        thousands = _first_id_value(ctc.get("thousands"))
        parts = []
        if lacs:
            parts.append(str(lacs) + " LPA")
        if thousands:
            parts.append(str(thousands) + " K")
        currency = profile.get("expectedCtcCurrency") or profile.get("currency") or ""
        if parts and currency:
            return f"{currency} {', '.join(parts)}"
        return ", ".join(parts)
    return str(ctc or "")


def _absolute_ctc_str(profile: dict) -> str:
    ctc = profile.get("absoluteCtc")
    if ctc is None:
        return ""
    currency = profile.get("currency") or ""
    try:
        val = int(float(ctc))
        formatted = f"{val:,}"
    except (TypeError, ValueError):
        formatted = str(ctc)
    return f"{currency} {formatted}" if currency else formatted


def _first_id_value(v) -> str:
    if isinstance(v, dict):
        return str(v.get("value", ""))
    if isinstance(v, (list, tuple)) and v:
        first = v[0]
        if isinstance(first, dict):
            return str(first.get("value", ""))
        return str(first)
    return str(v or "")


def _first_string(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and value:
        item = value[0]
        if isinstance(item, dict):
            return str(item.get("value", item.get("email", item.get("phone", "")))) or ""
        return str(item)
    return ""