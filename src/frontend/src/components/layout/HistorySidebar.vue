<template>
  <aside class="history-sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <!-- Header -->
    <div class="sidebar-header" @click="isCollapsed = !isCollapsed">
      <div v-if="!isCollapsed" class="sidebar-title">
        <v-icon icon="mdi-history" size="15" class="title-icon" />
        <span>Sessions</span>
        <span class="count-pill">{{ sessions.length }}</span>
      </div>
      <div class="header-spacer"></div>
      <button class="collapse-toggle" :title="isCollapsed ? 'Expand' : 'Collapse'">
        <v-icon :icon="isCollapsed ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="16" />
      </button>
    </div>

    <!-- Content Area -->
    <div v-if="!isCollapsed" class="sidebar-content">
      <button type="button" class="new-session-btn" @click.stop="handleNewSession">
        <v-icon icon="mdi-plus" size="14" />
        <span>New session</span>
      </button>

      <!-- Loading State -->
      <div v-if="isInitialLoading" class="loading-state">
        <div class="loading-shimmer">
          <div class="shimmer-bar"></div>
          <div class="shimmer-bar short"></div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="sessions.length === 0" class="empty-state">
        <div class="empty-icon-bg">
          <v-icon icon="mdi-chat-outline" size="24" class="opacity-40" />
        </div>
        <p>No conversations yet</p>
      </div>

      <div v-else class="sidebar-sections">
        <section class="sidebar-section">
          <button type="button" class="section-header section-toggle" @click="sessionsExpanded = !sessionsExpanded">
            <span class="section-header-main">
              <v-icon :icon="sessionsExpanded ? 'mdi-chevron-down' : 'mdi-chevron-right'" size="14" />
              <span class="section-label">Recent</span>
            </span>
            <span class="section-count">{{ sessions.length }}</span>
          </button>

          <div v-if="sessionsExpanded">
            <div v-if="sessions.length === 0" class="section-empty">
              Start a new question to create a conversation.
            </div>

            <div v-else class="history-list">
              <div
                v-for="session in sessions"
                :key="session.session_id"
                class="history-row session-row"
                :class="{ 'is-pinned': session.is_pinned, 'is-archived': session.is_archived, 'is-selected': selectedSessionId === session.session_id }"
                @click="handleSessionSelect(session)"
              >
                <div class="row-main">
                  <div class="row-copy">
                    <div class="row-title" :title="session.title || session.session_id">
                      {{ session.title || 'Untitled conversation' }}
                    </div>

                    <div class="row-meta">
                      <span class="row-date">{{ formatDate(session.last_activity_at) }}</span>
                      <span v-if="formatSessionSummary(session)" class="row-summary" :title="formatSessionSummary(session)">
                        {{ formatSessionSummary(session) }}
                      </span>
                    </div>
                  </div>

                  <div class="row-status-group">
                    <button
                      type="button"
                      class="pin-toggle"
                      :class="{ 'is-active': session.is_pinned }"
                      :title="session.is_pinned ? 'Unpin session' : 'Pin session'"
                      :aria-label="session.is_pinned ? 'Unpin session' : 'Pin session'"
                      :disabled="pinningSessionId === session.session_id"
                      @click.stop="toggleSessionPin(session)"
                    >
                      <v-progress-circular
                        v-if="pinningSessionId === session.session_id"
                        indeterminate
                        size="12"
                        width="2"
                        color="currentColor"
                      />
                      <v-icon v-else :icon="session.is_pinned ? 'mdi-pin' : 'mdi-pin-outline'" size="14" />
                    </button>
                    <span v-if="session.is_pinned" class="status-chip status-chip-pin">
                      <v-icon icon="mdi-pin" size="11" />
                      <span>Pinned</span>
                    </span>
                    <span v-if="getSessionDisplayStatus(session)" class="status-chip" :class="statusClass(getSessionDisplayStatus(session))">
                      {{ formatStatus(getSessionDisplayStatus(session)) }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

      </div>
    </div>
    
    <!-- Collapsed State Icons -->
    <div v-else class="collapsed-icons" @click="isCollapsed = false">
      <button type="button" class="collapsed-action-btn" title="New session" @click.stop="handleNewSession">
        <v-icon icon="mdi-plus" size="18" />
      </button>

      <div class="collapsed-icon-wrapper">
        <v-icon icon="mdi-chat-processing-outline" size="20" class="icon-dim" />
        <div v-if="sessions.length > 0" class="mini-fav-badge">{{ sessions.length }}</div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed, watch } from 'vue'
import { useHistory } from '@/composables/useHistory'

const emit = defineEmits(['select', 'collapse-change', 'new-session'])
const {
  sessions,
  sessionsLoading,
  fetchSessions,
  updateSession
} = useHistory()
const isCollapsed = ref(false)
const sessionsExpanded = ref(true)
const selectedSessionId = ref(null)
const pinningSessionId = ref(null)
const isInitialLoading = computed(() => sessionsLoading.value && sessions.value.length === 0)

// Emit collapse state changes to parent
watch(isCollapsed, (newVal) => {
  emit('collapse-change', newVal)
})

onMounted(() => {
  window.addEventListener('tako:session-loaded', handleSessionLoaded)
  window.addEventListener('tako:session-load-failed', handleSessionLoadFailed)
  window.addEventListener('tako:conversation-reset', handleConversationReset)
  void refreshSidebar()
})

onBeforeUnmount(() => {
  window.removeEventListener('tako:session-loaded', handleSessionLoaded)
  window.removeEventListener('tako:session-load-failed', handleSessionLoadFailed)
  window.removeEventListener('tako:conversation-reset', handleConversationReset)
})

const refreshSidebar = async () => {
  await fetchSessions()
}

const handleSessionSelect = (session) => {
  selectedSessionId.value = session.session_id
  emit('select', { kind: 'session', ...session })
}

const handleNewSession = () => {
  selectedSessionId.value = null
  emit('new-session')
}

const toggleSessionPin = async (session) => {
  if (!session?.session_id || pinningSessionId.value) return

  pinningSessionId.value = session.session_id
  try {
    await updateSession(session.session_id, {
      is_pinned: !Boolean(session.is_pinned)
    })
  } catch (error) {
    console.error('Failed to toggle session pin:', error)
  } finally {
    if (pinningSessionId.value === session.session_id) {
      pinningSessionId.value = null
    }
  }
}

const handleSessionLoaded = (event) => {
  const sessionId = event?.detail?.sessionId
  if (!sessionId) return

  selectedSessionId.value = sessionId
}

const handleSessionLoadFailed = (event) => {
  const sessionId = event?.detail?.sessionId
  if (!sessionId || selectedSessionId.value === sessionId) {
    selectedSessionId.value = null
  }
}

const handleConversationReset = () => {
  selectedSessionId.value = null
}

const parseApiTimestamp = (rawTimestamp) => {
  if (!rawTimestamp) return null

  const timestamp = String(rawTimestamp).trim()
  if (!timestamp) return null

  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp)
  const normalizedTimestamp = hasTimezone ? timestamp : `${timestamp}Z`
  const parsedDate = new Date(normalizedTimestamp)

  return Number.isNaN(parsedDate.getTime()) ? null : parsedDate
}

const formatDate = (dateStr) => {
  const date = parseApiTimestamp(dateStr)
  if (!date) return ''

  const now = new Date()
  const isSameYear = date.getFullYear() === now.getFullYear()

  const dateOptions = isSameYear
    ? { month: 'short', day: 'numeric' }
    : { year: 'numeric', month: 'short', day: 'numeric' }

  const calendarDate = date.toLocaleDateString([], dateOptions)
  const timeOfDay = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })

  return `${calendarDate}, ${timeOfDay}`
}

const formatSummary = (summary) => {
  if (!summary) return ''

  return summary
    .replace(/^#+\s*/gm, '')
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

const formatSessionSummary = (session) => {
  const summary = formatSummary(session.summary)
  if (summary) return summary

  if (session.source && session.source !== 'web') {
    return `Started from ${formatStatus(session.source)}`
  }

  return ''
}

const formatStatus = (status) => {
  if (!status) return 'Active'
  return status
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase())
}

const getSessionDisplayStatus = (session) => {
  if (session?.is_archived) return 'archived'

  const status = String(session?.status || '').trim().toLowerCase()
  if (!status || status === 'active') return null

  return status
}

const statusClass = (status) => {
  switch (status) {
    case 'completed':
      return 'status-chip-complete'
    case 'error':
    case 'failed':
      return 'status-chip-error'
    case 'archived':
      return 'status-chip-archived'
    default:
      return 'status-chip-active'
  }
}

defineExpose({ refresh: refreshSidebar })
</script>

<style scoped>
/* Main Sidebar Container - off-white, flat */
.history-sidebar {
  position: fixed;
  left: 0;
  top: var(--header-height, 56px);
  bottom: 0;
  width: var(--sidebar-width, 280px);
  background: rgba(255, 255, 255, 0.94);
  border-right: 1px solid var(--border-strong);
  display: flex;
  flex-direction: column;
  transition: width 0.25s ease;
  overflow: hidden;
  z-index: 80;
}

.history-sidebar.is-collapsed {
  width: var(--collapsed-sidebar-width, 48px);
}

/* Sidebar Header */
.sidebar-header {
  height: 44px;
  padding: 0 10px 0 14px;
  display: flex;
  align-items: center;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--border-strong);
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-family-display);
  font-weight: 650;
  font-size: 12px;
  color: var(--text-primary);
  letter-spacing: 0;
}

.title-icon {
  color: var(--text-muted);
}

.count-pill {
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 6px;
  background: #ffffff;
  color: var(--text-muted);
  border: 1px solid var(--border-color);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 600;
}

.header-spacer { flex: 1; }

.collapse-toggle {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}

.collapse-toggle:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

/* Sidebar Content Area */
.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 10px 10px 16px;
  display: flex;
  flex-direction: column;
}

.new-session-btn {
  width: 100%;
  min-height: 40px;
  margin-bottom: 12px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid rgba(var(--primary-rgb), 0.16);
  border-radius: 10px;
  background: rgba(var(--primary-rgb), 0.08);
  color: var(--primary);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, transform 0.15s ease;
}

.new-session-btn:hover {
  background: rgba(var(--primary-rgb), 0.12);
  border-color: rgba(var(--primary-rgb), 0.24);
  transform: translateY(-1px);
}

.sidebar-sections {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.sidebar-section-secondary {
  padding-top: 2px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 4px;
}

.section-toggle {
  width: 100%;
  border: none;
  background: transparent;
  cursor: pointer;
}

.section-header-main {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.section-label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.section-count {
  min-width: 18px;
  height: 18px;
  padding: 0 6px;
  border-radius: 999px;
  border: 1px solid var(--border-color);
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.section-empty {
  padding: 0 4px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

/* Custom Scrollbar */
.sidebar-content::-webkit-scrollbar { width: 6px; }
.sidebar-content::-webkit-scrollbar-track { background: transparent; }
.sidebar-content::-webkit-scrollbar-thumb {
  background: rgba(15, 23, 42, 0.08);
  border-radius: 6px;
}
.sidebar-content::-webkit-scrollbar-thumb:hover {
  background: rgba(15, 23, 42, 0.14);
}

/* History rows */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.history-row {
  position: relative;
  padding: 12px 12px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, transform 0.12s ease, box-shadow 0.12s ease;
  display: flex;
  flex-direction: column;
  gap: 0;
  border: 1px solid rgba(15, 23, 42, 0.12);
  background: rgba(var(--primary-rgb), 0.035);
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.history-row:hover {
  background: rgba(var(--primary-rgb), 0.055);
  border-color: rgba(15, 23, 42, 0.16);
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(15, 23, 42, 0.05);
}

.history-row.is-selected {
  border-color: rgba(var(--primary-rgb), 0.22);
  background: rgba(255, 255, 255, 0.98);
}

.history-row.session-row {
  background: rgba(15, 23, 42, 0.025);
}

.history-row.session-row.is-pinned {
  border-color: rgba(var(--primary-rgb), 0.24);
  background: rgba(var(--primary-rgb), 0.07);
}

.history-row.session-row.is-archived {
  opacity: 0.8;
}

.row-main {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.row-copy {
  min-width: 0;
  flex: 1;
}

.row-status-group {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 5px;
  flex-shrink: 0;
}

.pin-toggle {
  width: 24px;
  height: 24px;
  border-radius: 999px;
  border: 1px solid rgba(var(--primary-rgb), 0.12);
  background: rgba(var(--primary-rgb), 0.04);
  color: #4d678a;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background 0.12s ease, border-color 0.12s ease, color 0.12s ease, transform 0.12s ease;
}

.pin-toggle:hover:not(:disabled) {
  background: rgba(var(--primary-rgb), 0.1);
  border-color: rgba(var(--primary-rgb), 0.22);
  color: var(--primary);
  transform: translateY(-1px);
}

.pin-toggle.is-active {
  background: rgba(var(--primary-rgb), 0.12);
  border-color: rgba(var(--primary-rgb), 0.24);
  color: var(--primary);
}

.pin-toggle:disabled {
  cursor: wait;
  opacity: 0.82;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 7px;
  border-radius: 999px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  background: rgba(255, 255, 255, 0.85);
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 700;
  line-height: 1;
}

.status-chip-active {
  color: #245ea8;
  border-color: rgba(36, 94, 168, 0.18);
  background: rgba(36, 94, 168, 0.08);
}

.status-chip-complete {
  color: #1d4ed8;
  border-color: rgba(29, 78, 216, 0.16);
  background: rgba(29, 78, 216, 0.08);
}

.status-chip-error {
  color: #b42318;
  border-color: rgba(180, 35, 24, 0.18);
  background: rgba(180, 35, 24, 0.08);
}

.status-chip-archived {
  color: #6b7280;
  border-color: rgba(107, 114, 128, 0.18);
  background: rgba(107, 114, 128, 0.08);
}

.status-chip-pin {
  color: var(--primary);
  border-color: rgba(var(--primary-rgb), 0.18);
  background: rgba(var(--primary-rgb), 0.08);
}

.row-title {
  font-size: 12px;
  font-weight: 550;
  color: #183552;
  line-height: 1.4;
  letter-spacing: -0.01em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.row-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  font-size: 10px;
  color: var(--text-muted);
  line-height: 1.35;
  overflow: hidden;
  margin-top: 6px;
}

.row-date {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  min-height: 0;
  padding: 0;
  border-radius: 0;
  border: none;
  background: transparent;
  color: #4e647f;
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.row-summary {
  max-width: 100%;
  color: #415873;
  font-size: 10px;
  line-height: 1.45;
  padding-left: 10px;
  position: relative;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-summary::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0.5em;
  width: 4px;
  height: 4px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.22);
}

.history-row:hover .row-title {
  color: #102a44;
}

/* Empty/Loading States */
.empty-state, .loading-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: var(--text-muted);
  padding: 32px 12px;
}

.empty-icon-bg {
  width: 40px;
  height: 40px;
  background: transparent;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
  color: var(--text-faint);
}

.empty-state p {
  font-size: 12px;
  font-weight: 400;
  margin: 0;
  color: var(--text-muted);
}

/* Shimmer */
.loading-shimmer {
  width: 100%;
  padding: 8px 4px;
}
.shimmer-bar {
  height: 10px;
  background: linear-gradient(90deg, rgba(15,23,42,0.04) 0%, rgba(15,23,42,0.08) 50%, rgba(15,23,42,0.04) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 4px;
  margin-bottom: 8px;
}
.shimmer-bar.short { width: 60%; }

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Collapsed State Icons */
.collapsed-icons {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  cursor: pointer;
}

.collapsed-action-btn {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(var(--primary-rgb), 0.14);
  border-radius: 8px;
  background: rgba(var(--primary-rgb), 0.08);
  color: var(--primary);
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}

.collapsed-action-btn:hover {
  background: rgba(var(--primary-rgb), 0.12);
  border-color: rgba(var(--primary-rgb), 0.24);
}

.collapsed-icon-wrapper {
  position: relative;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 6px;
  color: var(--text-muted);
  transition: background 0.15s, color 0.15s;
}

.collapsed-icon-wrapper:hover {
  background: var(--surface-hover);
  color: var(--text-primary);
}

.icon-dim { opacity: 1; }

.mini-fav-badge {
  position: absolute;
  top: 0px;
  right: 0px;
  font-size: 8px;
  font-weight: 700;
  background: var(--primary);
  color: white;
  min-width: 12px;
  height: 12px;
  padding: 0 3px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
}
</style>
