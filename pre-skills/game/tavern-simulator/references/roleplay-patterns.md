# Roleplay Patterns

## Response Structure
[Action/narrative in asterisks]

[Spoken dialogue in quotes]

## Inference Priority
1. mes_example style (absolute formatting authority)
2. personality (core traits)
3. description (background/physical)
4. World book entries (lore)
5. scenario (scene context)
6. post_history_instructions (constraints)
7. system_prompt (overrides)

## Formatting Rules
- NPC dialogue: `<span class="npc-talk">` pink
- Player dialogue/action: `<span class="player-talk">` blue
- Options: 5-6 + custom, with emoji
- State panel: HTML details/summary (status-panel theme)
- Thinking process: hidden in `<!-- thinking ... response-->`

## Character Consistency
- Maintain mood/relationship/flags across turns
- Reference world book lore naturally
- Track key story events