@dataclass
class AgentOutput:
    status: str
    patch: Optional[str] = None
    cost_usd: float = 0.0
class AbstractAgentAdapter(ABC):
    @abstractmethod
    def configure(self, params: dict) -> None: ...
    @abstractmethod
    def run(self, agent_input: AgentInput, mode: ExecutionMode) -> AgentOutput: ...
    @abstractmethod
    def health_check(self) -> bool: ...
