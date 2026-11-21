from tradingagents.agents.state import AgentState


class ConditionalLogic:
    """Handles conditional logic for determining graph flow."""

    def __init__(self, max_debate_rounds=1, max_risk_discuss_rounds=1):
        """Initialize with configuration parameters."""
        self.max_debate_rounds = max_debate_rounds
        self.max_risk_discuss_rounds = max_risk_discuss_rounds

    def should_start_debate(self, state: AgentState) -> str:
        """Route from the analysts into the research debate, or straight past it.

        With ``max_debate_rounds == 0`` the debate must terminate immediately
        with a recorded reason (FR-02), not run a single Bull turn. Zero rounds
        means no side speaks; the Research Manager records the capped result.
        """
        if self.max_debate_rounds <= 0:
            return "Research Manager"
        return "Bull Researcher"

    def should_continue_debate(self, state: AgentState) -> str:
        """Determine if debate should continue."""

        if state["investment_debate_state"].get("converged"):
            # The latest completed round added no new claims on either side;
            # the manager can adjudicate now (FR-02).
            return "Research Manager"
        if (
            state["investment_debate_state"]["count"] >= 2 * self.max_debate_rounds
        ):  # max_debate_rounds turns each for bull and bear
            return "Research Manager"
        if state["investment_debate_state"]["current_response"].startswith("Bull"):
            return "Bear Researcher"
        return "Bull Researcher"

    def should_continue_risk_analysis(self, state: AgentState) -> str:
        """Determine if risk analysis should continue."""
        if (
            state["risk_debate_state"]["count"] >= 3 * self.max_risk_discuss_rounds
        ):  # max_risk_discuss_rounds turns each for the three risk analysts
            return "Portfolio Manager"
        if state["risk_debate_state"]["latest_speaker"].startswith("Aggressive"):
            return "Conservative Analyst"
        if state["risk_debate_state"]["latest_speaker"].startswith("Conservative"):
            return "Neutral Analyst"
        return "Aggressive Analyst"
