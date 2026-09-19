<template>
  <aside class="history-sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <!-- Header -->
    <div class="sidebar-header">
      <div v-if="!isCollapsed" class="sidebar-title">
        <v-icon icon="mdi-chat-outline" size="15" class="title-icon" />
        <span>Conversations</span>
      </div>
      <div class="header-spacer"></div>
      <button type="button" class="collapse-toggle" :title="isCollapsed ? 'Expand conversations' : 'Collapse conversations'" :aria-label="isCollapsed ? 'Expand conversations' : 'Collapse conversations'" :aria-expanded="!isCollapsed" @click="isCollapsed = !isCollapsed">
        <v-icon :icon="isCollapsed ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="16" />
      </button>
    </div>

    <div v-if="!isCollapsed" class="sidebar-actions">
      <button type="button" class="new-session-btn" @click.stop="handleNewSession">
        <span class="new-chat-icon"><v-icon icon="mdi-plus" size="14" /></span>
        <span>New chat session</span>
      </button>
    </div>

    <!-- Only the conversation list scrolls; New chat stays within reach. -->
    <div v-if="!isCollapsed" class="sidebar-content">
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
          <button type="button" class="section-header section-toggle" :aria-expanded="sessionsExpanded" @click="sessionsExpanded = !sessionsExpanded">
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
              >
                <button type="button" class="session-select" @click="handleSessionSelect(session)"
                  :aria-current="selectedSessionId === session.session_id ? 'true' : undefined"
                  :title="[session.title || 'Untitled conversation', formatSessionSummary(session)].filter(Boolean).join(' — ')">
                  <v-icon icon="mdi-message-text-outline" size="14" class="conversation-icon" aria-hidden="true" />
                  <span class="row-title">{{ session.title || 'Untitled conversation' }}</span>
                  <span class="row-meta">
                    <span class="row-date">{{ formatDate(session.last_activity_at) }}</span>
                    <span v-if="getSessionDisplayStatus(session)" class="status-chip" :class="statusClass(getSessionDisplayStatus(session))">
                      {{ formatStatus(getSessionDisplayStatus(session)) }}
                    </span>
                  </span>
                </button>
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
                  </div>
              </div>
            </div>
          </div>
        </section>

      </div>
    </div>
    
    <!-- Collapsed State Icons -->
    <div v-else class="collapsed-icons">
      <button type="button" class="collapsed-action-btn" title="New chat session" aria-label="New chat session" @click.stop="handleNewSession">
        <v-icon icon="mdi-plus" size="18" />
      </button>

      <button type="button" class="collapsed-icon-wrapper" aria-label="Expand conversations" @click="isCollapsed = false">
        <v-icon icon="mdi-chat-processing-outline" size="20" class="icon-dim" />
        <div v-if="sessions.length > 0" class="mini-fav-badge">{{ sessions.length }}</div>
      </button>
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
.history-row .pin-toggle { opacity: 0; }
.history-row:hover .pin-toggle, .history-row:focus-within .pin-toggle, .history-row .pin-toggle.is-active { opacity: 1; }
@media (hover: none) { .history-row .pin-toggle { opacity: 1; } }
/* A distinct navigation surface beside the cooler workspace canvas. */
.history-sidebar {
  position: fixed;
  left: 0;
  top: var(--header-height, 56px);
  bottom: 0;
  width: var(--sidebar-width, 280px);
  background: var(--surface-sidebar, #f8fafc);
  border-right: 1px solid #d8e0ec;
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
  height: 52px;
  flex-shrink: 0;
  padding: 0 12px 0 16px;
  display: flex;
  align-items: center;
  background: transparent;
  border-bottom: 0;
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-family: var(--font-family-display);
  font-weight: 600;
  font-size: 12px;
  color: var(--text-primary);
  letter-spacing: 0;
}

.title-icon {
  color: #5470aa;
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
  border: 1px solid #e2e7f0;
  background: #fff;
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
  min-height: 0;
  overflow-y: auto;
  padding: 12px 10px 16px;
  display: flex;
  flex-direction: column;
}

.sidebar-actions { padding: 0 10px 16px; }

.new-session-btn {
  width: 100%; min-height: 44px; padding: 8px 12px;
  display: flex; align-items: center; gap: 10px; text-align: left;
  border: 1px solid #375bcc; border-radius: 9px; background: var(--primary);
  color: #fff; font-size: 12px; font-weight: 550; cursor: pointer;
  box-shadow: 0 2px 4px rgba(62, 99, 221, 0.12);
  transition: background .15s, border-color .15s;
}
.new-session-btn:hover { background: var(--primary-hover); border-color: #2948a8; }
.new-chat-icon { display: grid; place-items: center; width: 22px; height: 22px; border-radius: 6px; background: rgba(255,255,255,.15); color: inherit; }

.sidebar-sections {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.sidebar-section-secondary {
  padding-top: 2px;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 0 8px 6px;
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
  font-size: 10px;
  font-weight: 600;
  letter-spacing: .065em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.section-count { display: inline-flex; align-items: center; justify-content: center; min-width: 20px; height: 18px; padding: 0 5px; border: 1px solid #e3e8f1; border-radius: 5px; background: #f3f6fb; color: #71809a; font-size: 10px; font-weight: 500; font-variant-numeric: tabular-nums; }

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

/* Compact rows keep titles and timestamps readable without nested cards. */
.history-list { display: flex; flex-direction: column; gap: 4px; }
.history-row { position: relative; border: 1px solid transparent; border-radius: 9px; transition: background .15s, border-color .15s; }
.history-row:hover { background: #f1f5fb; border-color: #e0e7f2; }
.history-row.is-selected { background: #eaf1ff; border-color: #cbdaf7; }
.history-row.is-selected::before { content: ''; position: absolute; left: 0; top: 12px; bottom: 12px; width: 2px; border-radius: 2px; background: var(--primary); }
.history-row.is-selected .row-title { color: #2f53a0; font-weight: 550; }
.conversation-icon { color: #9aa8bc; margin-top: 3px; }
.history-row.is-selected .conversation-icon { color: #5279cb; }
.history-row.is-archived { opacity: .75; }
.session-select { display: grid; grid-template-columns: 14px minmax(0, 1fr); column-gap: 8px; width: 100%; padding: 10px; border: 0; border-radius: inherit; background: transparent; text-align: left; cursor: pointer; }
.row-status-group { position: absolute; bottom: 6px; right: 5px; }
.history-sidebar button:focus-visible { outline: 2px solid var(--primary); outline-offset: -2px; }
.pin-toggle { display: grid; place-items: center; width: 24px; height: 24px; border: 0; border-radius: 6px; background: transparent; color: #7b8190; cursor: pointer; transition: background .15s, opacity .15s; }
.pin-toggle:hover, .pin-toggle.is-active { color: #526fc1; background: #e8eefb; }
.pin-toggle:disabled { cursor: wait; }
.status-chip { display: inline-flex; padding: 2px 5px; border-radius: 4px; font-size: 9px; line-height: 1.2; background: #eef0f4; color: #697080; }
.status-chip-active { color: #3a62b6; background: #edf2ff; }
.status-chip-complete { color: #217866; background: #e8f5ef; }
.status-chip-error { color: #b42318; background: #fff0ee; }
.row-title { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; overflow-wrap: anywhere; font-size: 12px; font-weight: 400; line-height: 1.5; color: #383e4c; }
.row-meta { grid-column: 2; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin-top: 4px; padding-right: 24px; }
.row-date { color: #7b8190; font-size: 10px; font-weight: 400; line-height: 1.5; }

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
  border: 0;
  background: transparent;
  cursor: pointer;
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
