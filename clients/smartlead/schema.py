from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


class StatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    DRAFTED = "DRAFTED"
    ARCHIVED = "ARCHIVED"
    STOPPED = "STOPPED"


class SchedulerCronValue(BaseModel):
    tz: str
    days: List[int]
    endHour: str
    startHour: str


class SmartleadCampaign(BaseModel):
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime
    status: StatusEnum
    name: str
    track_settings: List[str]
    scheduler_cron_value: Optional[SchedulerCronValue]
    min_time_btwn_emails: int
    max_leads_per_day: int
    stop_lead_settings: str
    enable_ai_esp_matching: bool
    send_as_plain_text: bool
    follow_up_percentage: float
    unsubscribe_text: Optional[str]
    parent_campaign_id: Optional[int]
    client_id: Optional[int]


class SmartleadLead(BaseModel):
    id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: str
    phone_number: Optional[str] = None
    company_name: Optional[str] = None
    website: Optional[str] = None
    location: Optional[str] = None
    custom_fields: Optional[Dict[str, Any]] = None
    linkedin_profile: Optional[str] = None
    company_url: Optional[str] = None
    is_unsubscribed: Optional[bool] = None


class SmartleadCampaignLead(BaseModel):
    campaign_lead_map_id: int
    status: str
    lead_category_id: Optional[int] = None
    created_at: datetime
    lead: SmartleadLead


class SmartleadGetCampaignLeadsResponse(BaseModel):
    total_leads: int
    offset: int
    limit: int
    data: List[SmartleadCampaignLead]


class SchedulerCronValue(BaseModel):
    tz: str
    days: List[int]
    endHour: str
    startHour: str


class SmartleadCampaign(BaseModel):
    id: int
    user_id: int
    created_at: str
    updated_at: str
    status: StatusEnum
    name: str
    track_settings: List[str]
    scheduler_cron_value: Optional[SchedulerCronValue]
    min_time_btwn_emails: int
    max_leads_per_day: int
    stop_lead_settings: str
    enable_ai_esp_matching: bool
    send_as_plain_text: bool
    follow_up_percentage: int
    unsubscribe_text: Optional[str]
    parent_campaign_id: Optional[int]
    client_id: Optional[int]


class CampaignLeadStats(BaseModel):
    total: int
    paused: int
    blocked: int
    stopped: int
    completed: int
    inprogress: int
    interested: int
    notStarted: int


class SmartleadCampaignStatistics(BaseModel):
    id: int
    user_id: int
    created_at: str
    status: StatusEnum
    name: str

    sent_count: str
    open_count: str
    click_count: str
    reply_count: str
    block_count: str
    total_count: str
    sequence_count: str
    drafted_count: str
    bounce_count: str
    unsubscribed_count: str

    sequence_count: str

    unique_open_count: str
    unique_click_count: str
    unique_sent_count: str

    client_id: int | None
    client_name: str | None
    client_email: str | None

    campaign_lead_stats: CampaignLeadStats


class SeqDelayDetails(BaseModel):
    delayInDays: int


class SmartleadCampaignSequenceVariant(BaseModel):
    id: int
    created_at: datetime  # z.string().datetime()
    updated_at: datetime  # z.string().datetime()
    is_deleted: bool
    subject: str
    email_body: str
    email_campaign_seq_id: int
    variant_label: str
    optional_email_body_1: Optional[str] = None
    variant_distribution_percentage: Optional[int] = None
    year: int


class SmartleadCampaignSequence(BaseModel):
    id: int
    created_at: datetime  # z.string().datetime()
    updated_at: datetime  # z.string().datetime()
    email_campaign_id: int
    seq_number: int
    subject: str
    email_body: str
    seq_delay_details: SeqDelayDetails
    sequence_variants: Optional[List[SmartleadCampaignSequenceVariant]] = None


class SeqDelayDetailsInput(BaseModel):
    delay_in_days: int = Field(..., alias="delay_in_days")


class SequenceVariantInput(BaseModel):
    subject: str
    id: Optional[int] = None
    email_body: str
    variant_label: str
    variant_distribution_percentage: Optional[float] = None  # number | null


class SmartleadCampaignSequenceInput(BaseModel):
    seq_number: int
    id: Optional[int] = None
    subject: Optional[str] = None
    email_body: Optional[str] = None
    seq_delay_details: Optional[SeqDelayDetailsInput] = None
    seq_variants: Optional[List[SequenceVariantInput]] = None
