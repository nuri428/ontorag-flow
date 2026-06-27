"""MemoryWhyProvider — ontorag-memory MemoryClient를 WhyContextProvider로 연결.

``ontorag-memory`` 패키지가 설치된 환경에서만 사용 가능한 선택적 어댑터.
``LlmAgentEngine`` 에 주입하면 허용 액션 URI마다 ``why()`` 를 호출해
근거·기각 대안·영향 관계를 LLM 프롬프트에 포함시킨다.

Usage::

    from ontorag_memory.client import MemoryClient
    from ontorag_flow.engines.memory_adapter import MemoryWhyProvider
    from ontorag_flow.engines.llm_agent import LlmAgentEngine

    async with await MemoryClient.create() as mem:
        provider = MemoryWhyProvider(mem)
        engine = LlmAgentEngine(llm_client, why_provider=provider)
        proposals = await engine.propose_next(case, process)
"""

from __future__ import annotations

from ontorag_flow.log import get_logger

logger = get_logger(__name__)


class MemoryWhyProvider:
    """``WhyContextProvider`` adapter backed by ``ontorag_memory.MemoryClient``.

    ``ontorag-memory`` 는 optional dependency이므로 이 클래스는 런타임에
    임포트될 때만 의존성이 필요하다. 패키지가 없으면 ImportError가 발생하며,
    그 경우 ``LlmAgentEngine`` 에 ``why_provider=None`` 을 전달하면 된다.

    Args:
        mem: 이미 생성된 ``MemoryClient`` 인스턴스.
            컨텍스트 매니저 안에서 사용하는 것을 권장한다
            (``async with await MemoryClient.create() as mem``).
    """

    def __init__(self, mem: object) -> None:
        self._mem = mem

    async def get_why_context(self, uri: str) -> str:
        """``uri`` 에 대한 why() 결과를 마크다운 문자열로 반환.

        why() 에 대한 기록이 없거나 오류 발생 시 빈 문자열을 반환한다.
        빈 문자열은 ``LlmAgentEngine._build_user_prompt`` 에서 무시된다.

        Args:
            uri: 액션 또는 엔티티 URI.

        Returns:
            마크다운 형식의 why 컨텍스트, 또는 빈 문자열.
        """
        try:
            result = await self._mem.why(uri)  # type: ignore[attr-defined]
            if not result.rationale and not result.decided_against and not result.influenced_by:
                return ""
            return result.to_context_str()
        except Exception as exc:
            logger.debug("why() failed for %s: %s", uri, exc)
            return ""
