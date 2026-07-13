"""Decision Profile interpretation content.

Keep question ids and answer ids aligned with
frontend/src/homeSections/HomePage/DecisionStyleAssessment/assessmentData.js.
This module intentionally contains descriptive language only: no scores, grades,
rankings, or comparative assessment labels.
"""

from app.email_templates.decision_profile_results import STYLE_PROFILES


QUESTION_PROFILES = [
    {
        "id": "q1_instinct_vs_research",
        "question": "When an important decision comes up, where do you naturally start?",
        "tendency": "Starting point",
        "options": {
            "q1_a": ("With my gut read of the situation", "You tend to notice an early direction before gathering much outside information."),
            "q1_b": ("Instinct first, then I check a few facts", "You often start with a read of the situation and then use facts to test it."),
            "q1_c": ("An even mix of instinct and information", "You tend to balance what feels true with what the available evidence says."),
            "q1_d": ("Research first, guided by instinct", "You usually look for useful information while still letting judgment guide the search."),
            "q1_e": ("By gathering information before I lean either way", "You prefer to understand the facts before leaning toward an option."),
        },
    },
    {
        "id": "q2_confidence",
        "question": "Once you have made an important decision, how settled do you usually feel?",
        "tendency": "Confidence after deciding",
        "options": {
            "q2_a": ("I often keep weighing it afterward", "You may continue processing the choice after the decision is technically made."),
            "q2_b": ("I sometimes keep weighing it", "You may revisit the decision when new concerns or information surface."),
            "q2_c": ("It varies from decision to decision", "Your certainty often depends on the context, stakes, and evidence available."),
            "q2_d": ("I usually feel settled", "Once you commit, you tend to move forward rather than repeatedly revisit the choice."),
            "q2_e": ("I almost always feel settled and move on", "You are comfortable committing and shifting energy toward action."),
        },
    },
    {
        "id": "q3_documenting",
        "question": "After you decide something important, how often do you write down why?",
        "tendency": "Documenting reasoning",
        "options": {
            "q3_a": ("Never", "Your reasoning may stay intuitive or conversational rather than written down."),
            "q3_b": ("Rarely", "You may preserve the decision outcome more often than the reasoning behind it."),
            "q3_c": ("Sometimes", "Your reasoning may be clear initially but harder to reconstruct later."),
            "q3_d": ("Often", "You often create enough traceability to explain the choice later."),
            "q3_e": ("Almost always", "You tend to preserve the reasoning behind important choices."),
            "q3_na": ("Not applicable", "Not enough information from this response."),
        },
    },
    {
        "id": "q4_alternatives",
        "question": "On a typical important decision, how many real alternatives do you seriously weigh?",
        "tendency": "Alternative exploration",
        "options": {
            "q4_none": ("None. I usually already know the option I want", "You may move quickly once one option feels clearly workable."),
            "q4_1_2": ("1–2", "You tend to compare a small number of practical paths before choosing."),
            "q4_3_5": ("3–5", "You usually explore several viable paths before choosing."),
            "q4_5_plus": ("More than 5", "You tend to keep the option space open long enough to understand multiple angles."),
            "q4_na": ("Not applicable", "Not enough information from this response."),
        },
    },
    {
        "id": "q5_explain_later",
        "question": "If someone asked weeks later why you chose what you did, how easily could you explain your reasoning?",
        "tendency": "Traceability",
        "options": {
            "q5_a": ("I'd find it hard to reconstruct", "The original reasoning may fade unless it is captured closer to the decision."),
            "q5_b": ("With some effort", "You can often reconstruct the reasoning, but it may take work."),
            "q5_c": ("Reasonably well", "You usually keep enough of the reasoning available to explain the choice."),
            "q5_d": ("Easily", "You tend to retain a clear line of reasoning."),
            "q5_e": ("I could walk through it step by step", "You tend to preserve the logic, evidence, and sequence behind the decision."),
            "q5_na": ("Not applicable", "Not enough information from this response."),
        },
    },
    {
        "id": "q6_what_would_change",
        "question": "When you decide, how clear are you about what new information would change your mind?",
        "tendency": "Assumption and evidence awareness",
        "options": {
            "q6_a": ("I rarely think about that", "You may focus more on making the choice than defining what would shift it."),
            "q6_b": ("Occasionally", "You sometimes name the evidence that would change your mind."),
            "q6_c": ("Sometimes", "You may recognize the key assumptions once the decision is taking shape."),
            "q6_d": ("Often", "You usually recognize which evidence could shift your position."),
            "q6_e": ("I'm usually very clear on it", "You tend to define the assumptions or signals that would change the decision."),
            "q6_na": ("Not applicable", "Not enough information from this response."),
        },
    },
    {
        "id": "q7_reflection",
        "question": "How often do you look back on past decisions to see how they turned out?",
        "tendency": "Reflection habit",
        "options": {
            "q7_a": ("Never", "You may prefer to keep moving rather than formally revisit past decisions."),
            "q7_b": ("Rarely", "You may reflect only when the outcome is especially visible or consequential."),
            "q7_c": ("Sometimes", "You reflect selectively rather than formally reviewing every decision."),
            "q7_d": ("Often", "You often learn from the gap between expected and actual outcomes."),
            "q7_e": ("Almost always", "You tend to turn decisions into a source of ongoing learning."),
        },
    },
]

QUESTION_BY_ID = {item["id"]: item for item in QUESTION_PROFILES}

STYLE_SECTIONS = {
    "evidence_builder": {
        "strengths": ["Traceable reasoning", "Evidence discipline", "Clear explanations"],
        "watch": ["You may keep searching after the decision already has enough shape to move forward."],
        "support": "Jaspen helps you organize evidence, pressure test assumptions, and preserve the reasoning behind the choice.",
        "questions": [
            "What information would genuinely change your choice?",
            "Are you still learning something useful, or delaying commitment?",
            "Which assumption carries the most risk?",
        ],
    },
    "fast_mover": {
        "strengths": ["Momentum", "Clear instincts", "Bias toward action"],
        "watch": ["You may move before the key assumptions are visible enough for others to follow."],
        "support": "Jaspen helps you keep speed while adding a lightweight check on assumptions, risks, and tradeoffs.",
        "questions": [
            "What assumption needs a quick check before you act?",
            "Who needs to understand the reasoning behind this move?",
            "What evidence would make you pause or adjust course?",
        ],
    },
    "thoughtful_explorer": {
        "strengths": ["Thoughtful exploration", "Option awareness", "Breadth of perspective"],
        "watch": ["You may keep too many options open after the strongest few have emerged."],
        "support": "Jaspen helps you compare alternatives cleanly, narrow the field, and keep the reasons visible.",
        "questions": [
            "Which options are meaningfully different from one another?",
            "What would make one path clearly stronger?",
            "What tradeoff are you most willing to accept?",
        ],
    },
    "consensus_seeker": {
        "strengths": ["Stakeholder awareness", "Durable alignment", "Shared understanding"],
        "watch": ["You may wait for complete agreement when clear ownership would be more helpful."],
        "support": "Jaspen helps you separate input from criteria, clarify who needs to weigh in, and document the final rationale.",
        "questions": [
            "Whose input changes the decision, and whose input informs it?",
            "Where is alignment necessary, and where is ownership enough?",
            "What criteria will help the group move forward?",
        ],
    },
    "practical_optimizer": {
        "strengths": ["Practical judgment", "Tradeoff awareness", "Fit with constraints"],
        "watch": ["You may optimize around immediate constraints before checking whether the goal has shifted."],
        "support": "Jaspen helps you make tradeoffs explicit, preserve why the path fits, and revisit the choice as conditions change.",
        "questions": [
            "What constraint matters most right now?",
            "Which tradeoff are you accepting intentionally?",
            "What would make this practical choice stop fitting?",
        ],
    },
    "reflective_analyzer": {
        "strengths": ["Reflection and learning", "Pattern recognition", "Careful reasoning"],
        "watch": ["You may replay a decision longer than the next action requires."],
        "support": "Jaspen helps you capture the original context, track what changed, and turn reflection into useful decision memory.",
        "questions": [
            "What changed between the original choice and the outcome?",
            "What pattern is worth remembering next time?",
            "What is the next action this reflection supports?",
        ],
    },
}


def answer_profile(question_id, answer_id):
    question = QUESTION_BY_ID.get(question_id)
    if not question:
        return {
            "question_id": question_id,
            "answer_id": answer_id,
            "question": question_id,
            "tendency": "Decision tendency",
            "answer_label": answer_id,
            "meaning": "Not enough information from this response.",
        }
    label, meaning = question["options"].get(
        answer_id,
        (answer_id, "Not enough information from this response."),
    )
    return {
        "question_id": question_id,
        "answer_id": answer_id,
        "question": question["question"],
        "tendency": question["tendency"],
        "answer_label": label,
        "meaning": meaning,
    }


def tendency_labels(answers):
    values = {}
    for question_id, answer_id in (answers or {}).items():
        if answer_id.endswith("_na"):
            values[question_id] = "Not enough information yet"
        elif answer_id.endswith(("_d", "_e")) or answer_id in {"q4_3_5", "q4_5_plus"}:
            values[question_id] = "Often"
        elif answer_id.endswith("_c") or answer_id == "q4_1_2":
            values[question_id] = "Sometimes"
        elif answer_id.endswith(("_a", "_b")) or answer_id == "q4_none":
            values[question_id] = "Less often"
        else:
            values[question_id] = "Usually"
    return values


def style_copy(style_key):
    base = STYLE_PROFILES.get(style_key) or STYLE_PROFILES["practical_optimizer"]
    extra = STYLE_SECTIONS.get(style_key) or STYLE_SECTIONS["practical_optimizer"]
    return {**base, **extra}
