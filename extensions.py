"""未来扩展的契约；第一阶段不运行爬虫或发送消息。"""
from typing import Protocol


class PublicTalentProvider(Protocol):
    """实现者必须使用已获授权的数据接口，保留来源、时间和授权依据。"""
    def fetch_authorized_records(self, *, query: str, authorization_reference: str) -> list[dict]: ...


class BusinessContactProvider(Protocol):
    """实现者必须在员工确认后发送，遵守平台规则、拒绝联系及频率限制。"""
    def send_reviewed_invitation(self, *, talent_id: int, text: str, approval_reference: str) -> dict: ...
