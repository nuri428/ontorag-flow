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
from datetime import UTC, datetime


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

        print(f"저장된 트리플: {saved}개")
        print(f"인시던트 URI: {incident_uri}")

        # 요약 확인
        summary = await mem.summarize(incident_uri)
        print("\n--- 요약 ---")
        print(summary)

        # patent-board와 연결된 인시던트 조회 (전이적 순회)
        related = await mem.find_related(
            "urn:ag:proj:patent-board",
            P.INVOLVES,
            direction="in",
            limit=10,
        )
        incident_uris = [r["uri"] for r in related if "incident" in r["uri"]]
        print(f"\npatent-board 관련 인시던트: {len(incident_uris)}개")
        for uri in incident_uris:
            print(f"  {uri}")

    return incident_uri


async def search_similar_incidents(keyword: str) -> None:
    """과거 인시던트에서 유사한 근본 원인 검색."""
    from ontorag_memory.client import MemoryClient  # noqa: PLC0415

    async with await MemoryClient.create() as mem:
        results = await mem.search_by_rationale(keyword, limit=10)
        print(f"\n'{keyword}' 관련 과거 인시던트 ({len(results)}개):")
        for r in results:
            if "incident" in r["subject"]:
                print(f"  {r['subject']}")
                print(f"    {r['snippet'][:80]}")


async def main() -> None:
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

    print(f"\n기록 완료: {incident_uri}")

    # 유사 인시던트 검색 (Fuseki 키워드)
    await search_similar_incidents("Fuseki")
    await search_similar_incidents("타임아웃")


if __name__ == "__main__":
    asyncio.run(main())
