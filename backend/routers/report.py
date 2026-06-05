"""旅行报告接口，负责生成与下载方案报告。"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.report_service import ReportService


router = APIRouter()
service = ReportService()


class ReportRequest(BaseModel):
    trip_result: dict


def _build_pdf_response(filename: str, content: bytes) -> StreamingResponse:
    quoted_name = quote(filename)
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted_name}',
        "Cache-Control": "no-store, max-age=0",
        "Pragma": "no-cache",
        "X-Content-Type-Options": "nosniff",
        "Content-Length": str(len(content)),
    }
    return StreamingResponse(iter([content]), media_type="application/pdf", headers=headers)


@router.post("/export")
@router.post("/generate", include_in_schema=False)
async def export_report(request: ReportRequest) -> StreamingResponse:
    """直接生成并返回 PDF 报告，避免服务器长期落盘。"""
    report = service.generate(request.trip_result)
    return _build_pdf_response(report.filename, report.content)
