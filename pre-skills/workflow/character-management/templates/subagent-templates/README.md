# Sub-Agent Prompt Template Library

A collection of 44 professional sub-agent prompt templates across 16 domains. Each role is a standalone Markdown file that can be used directly as a system prompt or trimmed and embedded into a multi-agent orchestration framework.

## Two Role Styles

| Style | Suitable Roles | Characteristics |
|---|---|---|
| **Grill Me** | Planning / Design / Architecture / Research | Progresses in stages (Initialize → Interrogate → Domain → Scenario → PreMortem → Conclude), one question per stage, with recommended answers and trade-offs, driven by a decision tree. |
| **Execution** | Development / Writing / Translation / Production | Pre-flight input check → standard workflow → output spec → Definition of Done (DoD) → clear boundary; when inputs are missing, list default assumptions instead of spinning in place. |

Selection principle: **upstream roles turn ambiguity into clarity (Grill Me); downstream roles turn clarity into deliverables (Execution)**. Both styles can be chained within the same pipeline.

## Domain & Role Map

### Software Engineering
```
Frontend/  01-Aesthetic · 02-InteractionDesigner · 03-FrontendArchitect · 04-FrontendDeveloper
Backend/   01-BackendArchitect · 02-DatabaseDesigner · 03-BackendDeveloper · 04-Auditor
Mobile/    01-MobileDesigner · 02-MobileDeveloper
DevOps/    01-DevOps · 02-SRE
General/   02-CodeReviewer
```
Recommended pipeline (new product feature): ProductManager → InteractionDesigner → Aesthetic → FrontendArchitect / BackendArchitect → DatabaseDesigner → FrontendDeveloper + BackendDeveloper (parallel) → CodeReviewer → Auditor → DevOps → SRE

### Product & User Research
```
Product/   01-ProductManager · 02-UserResearcher
General/   01-ProjectManager
```

### Design & Creative
```
Design/    01-Brander · 02-VisualDesigner (includes AI image-gen guidelines) · 03-Presenter (slides)
```
Recommended pipeline: Brander → VisualDesigner / Presenter

### Content & Marketing
```
Writing/   01-Curator · 02-Writer · 03-Editor
Marketing/ 01-MarketAnalyst · 02-Marketer · 03-Copywriter
```
Recommended pipeline (article): Curator → Writer → Editor
Recommended pipeline (campaign): MarketAnalyst → Marketer → Copywriter + VisualDesigner

### Data & AI
```
Data/      01-DataEngineer · 02-DataAnalyst · 03-DataViz
AI/        01-AIArchitect · 02-PromptEngineer · 03-MachineLearningEngineer
```
Recommended pipeline (data project): DataEngineer → DataAnalyst → DataViz
Recommended pipeline (AI application): AIArchitect → PromptEngineer / MachineLearningEngineer

### Finance & Legal
```
Finance/   01-MacroAnalyst · 02-IndustryResearcher · 03-RiskManager
Legal/     01-LegalResearcher · 02-ContractReviewer
```
Recommended pipeline (investment decision): MacroAnalyst → IndustryResearcher → RiskManager
Recommended pipeline (business partnership): LegalResearcher → ContractReviewer → RiskManager

### Research
```
Research/  01-LiteratureReviewer · 02-Experimentalist · 03-Academic
```
Recommended pipeline (research topic): LiteratureReviewer → Experimentalist → Academic

### Audio/Video & Games
```
AV/        01-Director (script / storyboard) · 02-Producer (includes TTS / sound-effect guidelines)
Games/     01-GameDesigner · 02-GameDeveloper
```

### General Functions
```
General/   01-ProjectManager · 02-CodeReviewer · 03-Localizer · 04-Documentarian
```

## Usage Notes

1. **Standalone use**: Use the whole file directly as a sub-agent system prompt.
2. **Pipeline orchestration**: Pass structured outputs between upstream and downstream roles (e.g., design tokens from Aesthetic become the input-checklist for FrontendDeveloper). The "Deliverables" and "Pre-flight Input Check" sections are already aligned for this.
3. **Trimming**: Each template is self-contained and can be shortened as needed — but keep the "Boundary (what I do not do)" section, which is the key to preventing role overlap.
4. **Grill Me owner**: The "owner" in Grill Me templates refers to the orchestrator (you or the main agent). The multi-turn question mode is suitable for interactive use; for fully automated pipelines, change the interrogation stage to "state default assumptions and label them".
5. **Decision-state tags**: `[OPEN]` / `[RESOLVED]` / `[DEFERRED]` / `[RISKY]` run through all Grill Me roles, making it easy to aggregate project status across roles.
