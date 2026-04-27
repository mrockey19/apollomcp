from typing import Literal

from pydantic import BaseModel


class PersonSummary(BaseModel):
    id: str
    name: str
    title: str | None = None
    company: str | None = None
    company_domain: str | None = None
    linkedin_url: str | None = None
    location: str | None = None


class EnrichedPerson(PersonSummary):
    email: str | None = None
    email_status: Literal[
        "verified", "unverified", "likely_to_engage", "unavailable"
    ] | None = None
    phone: str | None = None


class Company(BaseModel):
    id: str
    name: str
    domain: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    employee_range: str | None = None
    revenue_range: str | None = None
    technologies: list[str] = []
    linkedin_url: str | None = None
    location: str | None = None


class Contact(BaseModel):
    id: str
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    company: str | None = None


class EmailAccount(BaseModel):
    id: str
    email: str
    active: bool
    sender_name: str | None = None


class Sequence(BaseModel):
    id: str
    name: str
    active: bool
    num_steps: int | None = None
