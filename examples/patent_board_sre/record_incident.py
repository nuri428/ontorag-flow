"""patent_board SRE 인시던트 → ontorag-memory 기록 예제.

인시던트가 해결된 후 RCA 결과를 ontorag-memory에 기록한다.
미래 인시던트 분석 시 find_path_transitive / search_by_rationale / summarize 로 조회.

실행:
    uv run python examples/patent_board_sre/record_incident.py

필요 환경변수:
    FUSEKI_URL=http://localhost:3030  (기본값)
    ONTORAG_USER=greennuri
    ONTORAG_WORKSPACE=claudecode
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

logger = logging.getLogger(__name__)


async def record_incident(
    slug: str,
    severity: str,
    service: str,
    root_cause: str,
    fix_summary: str,
    affected_users: int,
) -> str:
    """인시던트 RCA 결과를 ontorag-memory에 저장하고 URI 반환."""
    from ontorag_memory.client import MemoryClient  # noqa: PLC0415
    from ontorag_memory.registry import P  # noqa: PLC0415

    today = datetime.now(tz=UTC).strftime("%Y-%m-%d")
    incident_uri = f"urn:ag:incident:{today}:{slug}"
    service_uri = f"urn:ag:service:{service}"

    async with await MemoryClient.create() as mem:
        saved = await mem.remember_bulk([
            # 인시던트 레이블
            {
                "subject": incident_uri,
                "predicate": P.LABEL,
                "object": f"[{severity}] {slug} — {today}",
            },
            # 근본 원인 (rationale)
            {
                "subject": incident_uri,
                "predicate": P.RATIONALE,
                "object": root_cause,
            },
            # 수정 요약 (content)
            {
                "subject": incident_uri,
                "predicate": P.CONTENT,
                "object": fix_summary,
            },
            # 날짜
            {
                "subject": incident_uri,
                "predicate": P.MADE_AT,
                "object": today,
            },
            # 영향 서비스 URI 연결
            {
                "subject": incident_uri,
                "predicate": P.INVOLVES,
                "object": service_uri,
                "object_is_uri": True,
            },
            # 영향 사용자 수 (description에 포함)
            {
                "subject": incident_uri,
                "predicate": P.DESCRIPTION,
                "object": f"영향 사용자: {affected_users}명 | severity: {severity}",
            },
            # patent-board 프로젝트와 연결
            {
                "subject": incident_uri,
                "predicate": P.INVOLVES,
                "object": "urn:ag:proj:patent-board",
                "object_is_uri": True,
            },
            # 서비스 레이블
            {
                "subject": service_uri,
                "predicate": P.LABEL,
                "object": service,
            },
        ])

        logger.info("저장된 트리플: %d개", saved)
        logger.info("인시던트 URI: %s", incident_uri)

        # 요약 확인
        summary = await mem.summarize(incident_uri)
        logger.info("\n--- 요약 ---\n%s", summary)

        # patent-board와 연결된 인시던트 조회 (전이적 순회)
        related = await mem.find_related(
            "urn:ag:proj:patent-board",
            P.INVOLVES,
            direction="in",
            limit=10,
        )
        incident_uris = [r["uri"] for r in related if "incident" in r["uri"]]
        logger.info("patent-board 관련 인시던트: %d개", len(incident_uris))
        for uri in incident_uris:
            logger.info("  %s", uri)

    return incident_uri


async def search_similar_incidents(keyword: str) -> None:
    """과거 인시던트에서 유사한 근본 원인 검색."""
    from ontorag_memory.client import MemoryClient  # noqa: PLC0415

    async with await MemoryClient.create() as mem:
        results = await mem.search_by_rationale(keyword, limit=10)
        logger.info("'%s' 관련 과거 인시던트 (%d개):", keyword, len(results))
        for r in results:
            if "incident" in r["subject"]:
                logger.info("  %s", r["subject"])
                logger.info("    %s", r["snippet"][:80])


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # 샘플 인시던트 기록
    incident_uri = await record_incident(
        slug="api-timeout-patent-search",
        severity="P2",
        service="patent-search-api",
        root_cause=(
            "Fuseki 쿼리 타임아웃: IPC 분류 JOIN이 인덱스 없이 실행됨. "
            "배포 시 새 Turtle 파일 로드 중 TDB2 락 경쟁 발생."
        ),
        fix_summary=(
            "1) Fuseki 쿼리 타임아웃 15s → 30s 상향 "
            "2) IPC JOIN에 Jena-text 인덱스 적용 "
            "3) 배포 중 롤링 재시작 시 락 대기 로직 추가"
        ),
        affected_users=142,
    )

    logger.info("기록 완료: %s", incident_uri)

    # 유사 인시던트 검색 (Fuseki 키워드)
    await search_similar_incidents("Fuseki")
    await search_similar_incidents("타임아웃")


if __name__ == "__main__":
    asyncio.run(main())
