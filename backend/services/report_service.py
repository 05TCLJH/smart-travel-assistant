"""基于报表库的样式化旅行报告生成服务。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from backend.core.public_views import sanitize_trip_result
from backend.core.paths import PROJECT_ROOT
from backend.core.settings import first_env


@dataclass(frozen=True)
class GeneratedReport:
    """面向下载响应的内存报告对象。"""

    filename: str
    content: bytes


class ReportService:
    """生成排版完善的中文 PDF 报告。"""

    PAGE_MARGIN = 15 * mm
    PAGE_WIDTH = A4[0] - PAGE_MARGIN * 2

    _PLANNER_LABELS: dict[str, str] = {
        "langgraph-react-planner": "多智能体行程规划",
        "langgraph_react_planner": "多智能体行程规划",
        "react-planner": "循环推理规划",
        "agent": "智能规划",
    }

    def __init__(self) -> None:
        self.font_name = self._register_font()
        self.styles = self._build_styles()

    def generate(self, trip_result: dict) -> GeneratedReport:
        trip_result = sanitize_trip_result(trip_result)
        filename = f"travel_report_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.pdf"
        buffer = BytesIO()
        self._draw_pdf(buffer, trip_result)
        return GeneratedReport(filename=filename, content=buffer.getvalue())

    def _register_font(self) -> str:
        alias = "TravelReportCn"
        if alias in pdfmetrics.getRegisteredFontNames():
            return alias

        candidates = self._font_candidates()
        for path in candidates:
            if not path.exists():
                continue
            try:
                pdfmetrics.registerFont(TTFont(alias, str(path)))
                return alias
            except Exception:
                continue

        fallback = "STSong-Light"
        if fallback not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(UnicodeCIDFont(fallback))
        return fallback

    @staticmethod
    def _font_candidates() -> list[Path]:
        configured = first_env("REPORT_FONT_PATHS", "REPORT_FONT_PATH", "PDF_FONT_PATH")
        config_paths: list[Path] = []
        for raw in configured.replace(";", ",").replace("\n", ",").split(","):
            candidate = raw.strip()
            if candidate:
                config_paths.append(Path(candidate))

        bundled_candidates = [
            PROJECT_ROOT / "assets" / "fonts" / "NotoSansSC-Regular.ttf",
            PROJECT_ROOT / "assets" / "fonts" / "SourceHanSansSC-Regular.otf",
            PROJECT_ROOT / "fonts" / "NotoSansSC-Regular.ttf",
            PROJECT_ROOT / "fonts" / "SourceHanSansSC-Regular.otf",
        ]
        system_candidates = [
            Path(r"C:\Windows\Fonts\msyh.ttc"),
            Path(r"C:\Windows\Fonts\Deng.ttf"),
            Path(r"C:\Windows\Fonts\simhei.ttf"),
            Path(r"C:\Windows\Fonts\simsun.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/SourceHanSansCN-Regular.otf"),
            Path("/usr/share/fonts/truetype/noto/NotoSansSC-Regular.ttf"),
            Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
            Path("/System/Library/Fonts/PingFang.ttc"),
            Path("/System/Library/Fonts/Hiragino Sans GB.ttc"),
            Path("/Library/Fonts/Arial Unicode.ttf"),
        ]

        seen: set[str] = set()
        ordered: list[Path] = []
        for path in [*config_paths, *bundled_candidates, *system_candidates]:
            key = str(path).strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            ordered.append(path)
        return ordered

    def _build_styles(self) -> dict[str, ParagraphStyle]:
        sample = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "ReportTitle",
                parent=sample["Title"],
                fontName=self.font_name,
                fontSize=24,
                leading=31,
                textColor=colors.HexColor("#173f3a"),
                spaceAfter=8,
                wordWrap="CJK",
            ),
            "subtitle": ParagraphStyle(
                "ReportSubtitle",
                parent=sample["BodyText"],
                fontName=self.font_name,
                fontSize=10.5,
                leading=16,
                textColor=colors.HexColor("#5f7d79"),
                spaceAfter=10,
                wordWrap="CJK",
            ),
            "section": ParagraphStyle(
                "SectionTitle",
                parent=sample["Heading2"],
                fontName=self.font_name,
                fontSize=15,
                leading=22,
                textColor=colors.HexColor("#1f6d68"),
                spaceBefore=4,
                spaceAfter=8,
                wordWrap="CJK",
            ),
            "body": ParagraphStyle(
                "Body",
                parent=sample["BodyText"],
                fontName=self.font_name,
                fontSize=10.2,
                leading=16.5,
                textColor=colors.HexColor("#213f3b"),
                spaceAfter=3,
                wordWrap="CJK",
            ),
            "body_soft": ParagraphStyle(
                "BodySoft",
                parent=sample["BodyText"],
                fontName=self.font_name,
                fontSize=9.2,
                leading=14.4,
                textColor=colors.HexColor("#607874"),
                wordWrap="CJK",
            ),
            "card_title": ParagraphStyle(
                "CardTitle",
                parent=sample["Heading3"],
                fontName=self.font_name,
                fontSize=11.6,
                leading=16,
                textColor=colors.HexColor("#183f3a"),
                spaceAfter=2,
                wordWrap="CJK",
            ),
            "tiny": ParagraphStyle(
                "Tiny",
                parent=sample["BodyText"],
                fontName=self.font_name,
                fontSize=8.4,
                leading=12.5,
                textColor=colors.HexColor("#6a817d"),
                wordWrap="CJK",
            ),
            "header": ParagraphStyle(
                "Header",
                parent=sample["BodyText"],
                fontName=self.font_name,
                fontSize=8.8,
                leading=10,
                textColor=colors.HexColor("#5d7571"),
                wordWrap="CJK",
            ),
        }

    def _draw_pdf(self, target: str | Path | BinaryIO, trip_result: dict) -> None:
        request = trip_result.get("trip_request", {}) or {}
        plan = trip_result.get("plan", {}) or {}
        weather = trip_result.get("weather", {}) or {}
        transport = trip_result.get("transport_plan", {}) or {}
        foods = trip_result.get("food_recommendations", []) or []
        lodgings = trip_result.get("lodging_recommendations", []) or []
        persona = trip_result.get("persona", {}) or {}
        tips = (trip_result.get("tips") or {}).get("tips", []) or []
        itinerary = plan.get("itinerary", []) or []

        destination = str(request.get("destination", "未设置") or "未设置").strip()
        days = request.get("days", "-")
        header_title = f"智能旅游助手 · {destination} {days}天行程"
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

        doc = SimpleDocTemplate(
            target,
            pagesize=A4,
            leftMargin=self.PAGE_MARGIN,
            rightMargin=self.PAGE_MARGIN,
            topMargin=22 * mm,
            bottomMargin=16 * mm,
            title=f"{destination}旅行方案报告",
            author="智能旅游助手",
        )

        story: list[Any] = []
        story.extend(self._build_cover(request, plan, weather, generated_at))
        story.append(self._section("方案总览"))
        story.append(self._summary_table(request, plan, weather))
        story.append(Spacer(1, 7))
        story.append(self._highlight_block(plan, weather, transport))

        story.append(Spacer(1, 10))
        story.append(self._section("每日行程"))
        for day in itinerary:
            story.append(KeepTogether(self._build_day_block(day)))
            story.append(Spacer(1, 8))

        story.append(self._section("门票与预算"))
        story.append(self._budget_table(plan))
        ticket_table = self._ticket_table(plan)
        if ticket_table is not None:
            story.append(Spacer(1, 8))
            story.append(ticket_table)

        story.append(Spacer(1, 8))
        story.append(self._section("住宿与当地味道"))
        story.append(self._support_table(transport, foods, lodgings))

        story.append(Spacer(1, 8))
        story.append(self._section("贴心提醒"))
        story.extend(self._tip_blocks(tips))

        def draw_page_chrome(canvas, _doc) -> None:
            self._draw_page_frame(canvas, header_title, generated_at)

        doc.build(story, onFirstPage=draw_page_chrome, onLaterPages=draw_page_chrome)

    @classmethod
    def _planner_mode_label(cls, raw: Any) -> str:
        key = str(raw or "").strip().lower().replace("_", "-")
        return cls._PLANNER_LABELS.get(key, "智能规划")

    @staticmethod
    def _money(value: Any) -> str:
        try:
            return f"¥{float(value):,.0f}"
        except (TypeError, ValueError):
            return f"¥{value}"

    @staticmethod
    def _safe_text(value: Any) -> str:
        return escape(str(value or "").strip()).replace("\n", "<br/>")

    def _paragraph(self, text: Any, style_name: str) -> Paragraph:
        return Paragraph(self._safe_text(text), self.styles[style_name])

    def _rich_paragraph(self, text: str, style_name: str) -> Paragraph:
        return Paragraph(text, self.styles[style_name])

    def _build_cover(self, request: dict[str, Any], plan: dict[str, Any], weather: dict[str, Any], generated_at: str) -> list[Any]:
        destination = str(request.get("destination", "未设置") or "未设置").strip()
        days = request.get("days", "-")
        hero = Table(
            [
                [self._rich_paragraph("智能旅游助手 · 旅行方案", "header")],
                [self._rich_paragraph(f"{self._safe_text(destination)} · {self._safe_text(days)}天行程", "title")],
                [self._rich_paragraph(f"生成时间：{self._safe_text(generated_at)}", "subtitle")],
            ],
            colWidths=[self.PAGE_WIDTH],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef8f6")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d4ebe7")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 16),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 16),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("ROUNDEDCORNERS", [16, 16, 16, 16]),
                ]
            ),
        )

        metrics = Table(
            [
                [
                    self._metric_card("出发日期", str(request.get("start_date", "-"))),
                    self._metric_card("总预算", self._money(request.get("budget", "-"))),
                ],
                [
                    self._metric_card("天气评级", str(weather.get("rating", "待确认"))),
                    self._metric_card("预计花费", self._money(plan.get("estimated_total_cost", "-"))),
                ],
            ],
            colWidths=[(self.PAGE_WIDTH - 6) / 2, (self.PAGE_WIDTH - 6) / 2],
            style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]),
        )
        return [hero, Spacer(1, 10), metrics, Spacer(1, 6)]

    def _metric_card(self, label: str, value: str) -> Table:
        return Table(
            [[self._paragraph(label, "tiny")], [self._paragraph(value, "card_title")]],
            colWidths=[(self.PAGE_WIDTH - 18) / 2],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("ROUNDEDCORNERS", [12, 12, 12, 12]),
                ]
            ),
        )

    def _summary_table(self, request: dict[str, Any], plan: dict[str, Any], weather: dict[str, Any]) -> Table:
        rows = [
            ["目的地", str(request.get("destination", "-")), "天数", f"{request.get('days', '-')} 天"],
            ["预算", self._money(request.get("budget", "-")), "天气", str(weather.get("rating", "待确认"))],
            ["预计花费", self._money(plan.get("estimated_total_cost", "-")), "规划模式", self._planner_mode_label(plan.get("planner_provider"))],
        ]
        formatted = []
        for row in rows:
            formatted.append([self._paragraph(cell, "body" if index % 2 else "tiny") for index, cell in enumerate(row)])
        return Table(
            formatted,
            colWidths=[26 * mm, 58 * mm, 26 * mm, 60 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#e5f1ef")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            ),
        )

    def _highlight_block(self, plan: dict[str, Any], weather: dict[str, Any], transport: dict[str, Any]) -> Table:
        preferred = "、".join(str(item).strip() for item in (plan.get("preferred_places", []) or [])[:6] if str(item).strip()) or "按当天喜好灵活取舍"
        summary = str(transport.get("summary", "") or "").strip() or "这版方案更注重景点取舍、顺路感和落地后的调整空间。"
        rows = [
            [self._paragraph("行程亮点", "tiny"), self._paragraph(preferred, "body")],
            [self._paragraph("天气建议", "tiny"), self._paragraph(weather.get("advice", "出发前请再次确认实时天气。"), "body")],
            [self._paragraph("动线提醒", "tiny"), self._paragraph(summary, "body")],
        ]
        return Table(
            rows,
            colWidths=[24 * mm, self.PAGE_WIDTH - 24 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fbfdfc")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#eaf4f2")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        )

    def _build_day_block(self, day: dict[str, Any]) -> list[Any]:
        title = Table(
            [
                [
                    self._rich_paragraph(f"Day {self._safe_text(day.get('day', '-'))}", "card_title"),
                    self._rich_paragraph(self._safe_text(day.get("theme", "待补充")), "body_soft"),
                ]
            ],
            colWidths=[25 * mm, self.PAGE_WIDTH - 25 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef8f6")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROUNDEDCORNERS", [14, 14, 14, 14]),
                ]
            ),
        )

        points = [str(item).strip() for item in (day.get("route_points", []) or []) if str(item).strip()]
        point_line = "、".join(points) or "当天景点待现场微调"
        route_line = self._format_day_route_summary(day)

        summary = Table(
            [
                [self._paragraph("景点主线", "tiny"), self._paragraph(point_line, "body")],
                [self._paragraph("当天节奏", "tiny"), self._paragraph(route_line, "body_soft")],
            ],
            colWidths=[22 * mm, self.PAGE_WIDTH - 22 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e3efed")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#edf5f3")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        )

        flows: list[Any] = [title, Spacer(1, 4), summary]

        timeline_rows = [[self._paragraph("时间", "tiny"), self._paragraph("安排", "tiny")]]
        for item in day.get("timeline", []) or []:
            timeline_rows.append(
                [
                    self._paragraph(item.get("time", "--:--"), "body_soft"),
                    self._paragraph(item.get("activity", "待补充"), "body"),
                ]
            )

        if len(timeline_rows) > 1:
            flows.append(Spacer(1, 5))
            flows.append(
                Table(
                    timeline_rows,
                    colWidths=[24 * mm, self.PAGE_WIDTH - 24 * mm],
                    repeatRows=1,
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5faf9")),
                            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#dfeceb")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#edf4f3")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    ),
                )
            )

        note = str(day.get("day_note", "") or "").strip()
        if note:
            flows.append(Spacer(1, 5))
            flows.append(
                Table(
                    [[self._paragraph("关键提醒", "tiny")], [self._paragraph(note, "body")]],
                    colWidths=[self.PAGE_WIDTH],
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff8ec")),
                            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#f3d59b")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 7),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                            ("ROUNDEDCORNERS", [12, 12, 12, 12]),
                        ]
                    ),
                )
            )
        return flows

    def _budget_table(self, plan: dict[str, Any]) -> Table:
        rows = [["项目", "金额"]]
        for label, amount in (plan.get("cost_breakdown", {}) or {}).items():
            rows.append([self._paragraph(label, "body"), self._paragraph(self._money(amount), "body")])
        note = str(plan.get("budget_note", "") or "").strip()
        table = Table(
            rows,
            colWidths=[52 * mm, self.PAGE_WIDTH - 52 * mm],
            repeatRows=1,
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5faf9")),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#eaf4f2")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ]
            ),
        )
        if not note:
            return table
        return Table(
            [
                [table],
                [
                    Table(
                        [[self._paragraph("预算提示", "tiny")], [self._paragraph(note, "body_soft")]],
                        colWidths=[self.PAGE_WIDTH],
                        style=TableStyle(
                            [
                                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7fbff")),
                                ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d7e6f6")),
                                ("LEFTPADDING", (0, 0), (-1, -1), 10),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                                ("TOPPADDING", (0, 0), (-1, -1), 8),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                                ("ROUNDEDCORNERS", [12, 12, 12, 12]),
                            ]
                        ),
                    )
                ],
            ],
            colWidths=[self.PAGE_WIDTH],
            style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]),
        )

    def _ticket_table(self, plan: dict[str, Any]) -> Table | None:
        detail = (plan.get("budget_detail") or {}).get("tickets") or {}
        lines = detail.get("lines", []) or []
        summary = detail.get("summary", {}) or {}
        if not lines:
            return None

        intro = (
            "以下门票与预约金额均为经验估算，用来帮助你把握整体预算轮廓。"
            "正式出发前，请逐个景点以官方预约页、景区公告或正规售票平台信息为准。"
        )

        rows: list[list[Any]] = [
            [self._paragraph("门票与预约明细", "card_title")],
            [self._paragraph(intro, "body_soft")],
        ]

        line_rows = [
            [
                self._paragraph("日次", "tiny"),
                self._paragraph("地点", "tiny"),
                self._paragraph("金额", "tiny"),
                self._paragraph("来源", "tiny"),
                self._paragraph("提醒", "tiny"),
            ]
        ]
        for line in lines:
            line_rows.append(
                [
                    self._paragraph(f"Day {line.get('day', '-')}", "body_soft"),
                    self._paragraph(line.get("place", "景点"), "body"),
                    self._paragraph(self._money(line.get("amount", 0)), "body"),
                    self._paragraph(line.get("source_label", "经验估算"), "body"),
                    self._paragraph(line.get("verification_hint") or line.get("note") or "", "body_soft"),
                ]
            )

        rows.append(
            [
                Table(
                    line_rows,
                    colWidths=[18 * mm, 38 * mm, 22 * mm, 24 * mm, self.PAGE_WIDTH - 102 * mm],
                    repeatRows=1,
                    style=TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f5faf9")),
                            ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                            ("INNERGRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#e9f2f1")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 8),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                            ("TOPPADDING", (0, 0), (-1, -1), 6),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ]
                    ),
                )
            ]
        )
        return Table(
            rows,
            colWidths=[self.PAGE_WIDTH],
            style=TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]),
        )

    def _support_table(self, transport: dict[str, Any], foods: list[dict[str, Any]], lodgings: list[dict[str, Any]]) -> Table:
        daily_stays = transport.get("daily_stays", []) or []
        stay_rows = [f"Day {item.get('day', '-')} 入住 {item.get('hotel_name', '待补充')}" for item in daily_stays[:6]]
        if not stay_rows:
            stay_rows = [str(item.get("name", "")).strip() for item in lodgings[:4] if str(item.get("name", "")).strip()]
        food_rows = [str(item.get("name", "")).strip() for item in foods[:5] if str(item.get("name", "")).strip()]
        rows = [
            [self._paragraph("交通建议", "tiny"), self._paragraph(f"{transport.get('suggested_mode', '待补充')}；{transport.get('summary', '当天按实时路况灵活微调即可。')}", "body")],
            [self._paragraph("住宿安排", "tiny"), self._paragraph("、".join(stay_rows) or "住宿仍可根据当天体力再做取舍。", "body")],
            [self._paragraph("当地味道", "tiny"), self._paragraph("、".join(food_rows) or "到了现场，找一家顺眼的小店慢慢吃，通常比赶点评分更有惊喜。", "body")],
        ]
        return Table(
            rows,
            colWidths=[24 * mm, self.PAGE_WIDTH - 24 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#d8ece8")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e9f3f1")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            ),
        )

    def _tip_blocks(self, tips: list[Any]) -> list[Any]:
        normalized = self._normalize_tips(tips)
        if not normalized:
            normalized = [
                {
                    "tag": "提醒",
                    "title": "出发前把天气、预约和返程再核一遍",
                    "body": "临近出发时，再看一次天气、预约状态和返程接驳方式，通常就能避开大部分临场慌乱。",
                    "tone": "soft",
                }
            ]
        blocks: list[Any] = []
        for item in normalized:
            tone = str(item.get("tone", "soft")).strip()
            background = {
                "alert": colors.HexColor("#fff8ec"),
                "warm": colors.HexColor("#f5fbff"),
                "soft": colors.HexColor("#fbfdfc"),
            }.get(tone, colors.HexColor("#fbfdfc"))
            border = {
                "alert": colors.HexColor("#f2d69b"),
                "warm": colors.HexColor("#d5e6f5"),
                "soft": colors.HexColor("#d8ece8"),
            }.get(tone, colors.HexColor("#d8ece8"))

            card = Table(
                [
                    [self._paragraph(item.get("tag", "提醒"), "tiny"), self._paragraph(item.get("title", "出行提醒"), "card_title")],
                    ["", self._paragraph(item.get("body", ""), "body")],
                ],
                colWidths=[22 * mm, self.PAGE_WIDTH - 22 * mm],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), background),
                        ("BOX", (0, 0), (-1, -1), 1, border),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 8),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("ROUNDEDCORNERS", [12, 12, 12, 12]),
                    ]
                ),
            )
            blocks.append(KeepTogether([card, Spacer(1, 6)]))
        return blocks

    def _normalize_tips(self, tips: list[Any]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        for index, item in enumerate(tips):
            if isinstance(item, dict):
                body = str(item.get("body") or item.get("text") or "").strip()
                if not body:
                    continue
                normalized.append(
                    {
                        "tag": str(item.get("tag") or f"提醒 {index + 1}").strip(),
                        "title": str(item.get("title") or "出行提醒").strip(),
                        "body": body,
                        "tone": str(item.get("tone") or "soft").strip(),
                    }
                )
            else:
                text = str(item or "").strip()
                if not text:
                    continue
                normalized.append(
                    {
                        "tag": f"提醒 {index + 1}",
                        "title": "出行提醒",
                        "body": text,
                        "tone": "soft",
                    }
                )
        return normalized

    def _section(self, title: str) -> Paragraph:
        return Paragraph(self._safe_text(title), self.styles["section"])

    def _format_day_route_summary(self, day: dict[str, Any]) -> str:
        geometry = day.get("route_geometry", {}) or {}
        status = str(geometry.get("status", "") or "").strip().lower()
        dist_m = float(geometry.get("distance_m", 0) or 0)
        dur_s = float(geometry.get("duration_s", 0) or 0)
        if dist_m > 0:
            dist_text = f"{dist_m / 1000:.1f} 公里" if dist_m >= 1000 else f"{int(dist_m)} 米"
            if dur_s >= 3600:
                duration_text = f"{dur_s / 3600:.1f} 小时"
            elif dur_s >= 60:
                duration_text = f"{max(1, int(round(dur_s / 60)))} 分钟"
            else:
                duration_text = f"{int(dur_s)} 秒"
            return f"当天动线约 {dist_text}，按正常路况预留 {duration_text} 会更稳妥。"
        if status in {"metrics_only", "approximate", "failed", "unavailable", "no_waypoints"}:
            return "当天景点已经尽量往同一片区域收拢，到了现场跟着实时导航走，会比死卡固定线路更从容。"
        return "当天节奏已尽量按顺路感排开，实际走法可按现场人流和体力再微调。"

    def _draw_page_frame(self, canvas, header_title: str, generated_at: str) -> None:
        canvas.saveState()
        width, height = A4
        canvas.setStrokeColor(colors.HexColor("#d8ece8"))
        canvas.setLineWidth(0.7)
        canvas.line(self.PAGE_MARGIN, height - 14 * mm, width - self.PAGE_MARGIN, height - 14 * mm)
        canvas.line(self.PAGE_MARGIN, 12 * mm, width - self.PAGE_MARGIN, 12 * mm)

        canvas.setFont(self.font_name, 8.8)
        canvas.setFillColor(colors.HexColor("#5f7873"))
        canvas.drawString(self.PAGE_MARGIN, height - 10.5 * mm, header_title)
        canvas.drawRightString(width - self.PAGE_MARGIN, height - 10.5 * mm, generated_at)

        canvas.drawString(self.PAGE_MARGIN, 8.2 * mm, "智能旅游助手 · 行程参考")
        canvas.drawRightString(width - self.PAGE_MARGIN, 8.2 * mm, f"第 {canvas.getPageNumber()} 页")
        canvas.restoreState()
