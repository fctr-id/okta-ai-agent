import { computed, ref, watch } from 'vue'

export function useConversationCollapse(turns) {
    const collapsedTurnKeys = ref(new Set())
    const sectionCollapseRevisions = ref({})
    const setTurnCollapsed = (key, collapsed) => {
        const next = new Set(collapsedTurnKeys.value)
        if (collapsed) next.add(key)
        else next.delete(key)
        collapsedTurnKeys.value = next
    }
    const collapseTurns = (targets) => {
        const next = new Set(collapsedTurnKeys.value)
        const revisions = { ...sectionCollapseRevisions.value }
        for (const turn of targets) {
            next.add(turn.key)
            revisions[turn.key] = (revisions[turn.key] || 0) + 1
        }
        collapsedTurnKeys.value = next
        sectionCollapseRevisions.value = revisions
    }
    watch(() => turns.value.map(turn => turn.key), keys => {
        const present = new Set(keys)
        collapsedTurnKeys.value = new Set([...collapsedTurnKeys.value].filter(key => present.has(key)))
        sectionCollapseRevisions.value = Object.fromEntries(
            Object.entries(sectionCollapseRevisions.value).filter(([key]) => present.has(key)),
        )
    })
    return {
        collapsedTurnKeys, sectionCollapseRevisions, setTurnCollapsed,
        hasExpandedPreviousTurns: computed(() => turns.value.slice(0, -1).some(turn => !collapsedTurnKeys.value.has(turn.key))),
        collapsePreviousTurns: () => collapseTurns(turns.value.slice(0, -1)),
        collapseRestoredTurns: () => collapseTurns(turns.value),
        collapseForFollowUp: () => collapseTurns(turns.value),
    }
}
