<template>
  <aside class="history-sidebar" :class="{ 'is-collapsed': isCollapsed }">
    <!-- Header -->
    <div class="sidebar-header" @click="isCollapsed = !isCollapsed">
      <div v-if="!isCollapsed" class="sidebar-title">
        <div class="title-icon-bg">
          <v-icon icon="mdi-history" size="16" class="title-icon" />
        </div>
        <span>Recent Activity</span>
      </div>
      <div class="header-spacer"></div>
      <button class="collapse-toggle" :title="isCollapsed ? 'Expand' : 'Collapse'">
        <v-icon :icon="isCollapsed ? 'mdi-chevron-right' : 'mdi-chevron-left'" size="18" />
      </button>
    </div>

    <!-- Content Area -->
    <div v-if="!isCollapsed" class="sidebar-content">
      <!-- Loading State -->
      <div v-if="loading && history.length === 0" class="loading-state">
        <div class="loading-shimmer">
          <div class="shimmer-bar"></div>
          <div class="shimmer-bar short"></div>
        </div>
      </div>

      <!-- Empty State -->
      <div v-else-if="history.length === 0" class="empty-state">
        <div class="empty-icon-bg">
          <v-icon icon="mdi-text-search-variant" size="24" class="opacity-40" />
        </div>
        <p>No queries found</p>
      </div>

      <!-- History List -->
      <div v-else class="history-list">
        <div 
          v-for="item in history" 
          :key="item.id" 
          class="history-card" 
          :class="{ 'is-favorite': item.is_favorite }"
          @click="$emit('select', item)"
        >
          <div class="card-glow"></div>
          
          <!-- Query Title -->
          <div class="card-query" :title="item.query_text">
            {{ item.query_text }}
          </div>
          
          <!-- Results Summary -->
          <div v-if="item.results_summary" class="card-summary">
            <v-icon icon="mdi-circle-small" size="12" class="mr-1" />
            {{ item.results_summary }}
          </div>

          <!-- Card Footer -->
          <div class="card-footer">
            <span class="card-date">{{ formatDate(item.last_run_at) }}</span>
          </div>
          
          <!-- Always Visible Actions -->
          <div class="card-actions">
            <button 
              class="card-btn fav-btn" 
              :class="{ 'active': item.is_favorite }"
              @click.stop="toggleFav(item)"
            >
              <v-icon :icon="item.is_favorite ? 'mdi-star' : 'mdi-star-outline'" size="14" />
              <span>{{ item.is_favorite ? 'Saved' : 'Save' }}</span>
            </button>
            
            <div class="btn-divider"></div>

            <button 
              class="card-btn exec-btn" 
              @click.stop="$emit('execute', item)"
            >
              <v-icon icon="mdi-play" size="14" />
              <span>Run</span>
            </button>
          </div>
        </div>
      </div>
    </div>
    
    <!-- Collapsed State Icons -->
    <div v-else class="collapsed-icons" @click="isCollapsed = false">
      <div class="collapsed-icon-wrapper">
        <v-icon icon="mdi-history" size="20" class="icon-dim" />
        <div v-if="favoritesCount > 0" class="mini-fav-badge">{{ favoritesCount }}</div>
      </div>
    </div>
  </aside>
</template>

<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { useHistory } from '@/composables/useHistory'

const emit = defineEmits(['select', 'execute', 'collapse-change'])
const { history, loading, fetchHistory, toggleFavorite } = useHistory()
const isCollapsed = ref(false)

const favoritesCount = computed(() => history.value.filter(h => h.is_favorite).length)

// Emit collapse state changes to parent
watch(isCollapsed, (newVal) => {
  emit('collapse-change', newVal)
})

onMounted(() => {
  fetchHistory()
})

const toggleFav = async (item) => {
  await toggleFavorite(item.id, !item.is_favorite)
}

const formatDate = (dateStr) => {
  if (!dateStr) return ''
  const date = new Date(dateStr)
  const now = new Date()
  const isToday = date.toDateString() === now.toDateString()
  
  if (isToday) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } else {
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' })
  }
}

defineExpose({ refresh: fetchHistory })
</script>

<style scoped>
/* Main Sidebar Container */
.history-sidebar {
  position: fixed;
  left: 0;
  top: 64px; /* Below header */
  bottom: 0; /* Stick to bottom instead of calc height */
  width: 280px;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(24px) saturate(180%);
  -webkit-backdrop-filter: blur(24px) saturate(180%);
  border-right: 1px solid rgba(255, 255, 255, 0.4);
  display: flex;
  flex-direction: column;
  transition: all 0.5s cubic-bezier(0.16, 1, 0.3, 1);
  overflow: hidden;
  z-index: 80;
  box-shadow: 1px 0 0 rgba(0, 0, 0, 0.02);
}

.history-sidebar.is-collapsed {
  width: 64px;
  background: rgba(255, 255, 255, 0.4);
}

/* Sidebar Header */
.sidebar-header {
  height: 60px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  border-bottom: 1px solid rgba(0, 0, 0, 0.03);
  cursor: pointer;
  background: rgba(255, 255, 255, 0.2);
}

.sidebar-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-family-display);
  font-weight: 700;
  font-size: 13px;
  color: #1e293b;
  letter-spacing: -0.01em;
}

.title-icon-bg {
  width: 28px;
  height: 28px;
  background: rgba(76, 100, 226, 0.08);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #4C64E2;
}

.header-spacer { flex: 1; }

.collapse-toggle {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  border: none;
  background: transparent;
  cursor: pointer;
  color: #94a3b8;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.collapse-toggle:hover {
  background: rgba(0, 0, 0, 0.04);
  color: #475569;
}

/* Sidebar Content Area */
.sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

/* Custom Scrollbar */
.sidebar-content::-webkit-scrollbar { width: 4px; }
.sidebar-content::-webkit-scrollbar-track { background: transparent; }
.sidebar-content::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.05);
  border-radius: 10px;
}

/* History Cards List */
.history-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.history-card {
  position: relative;
  padding: 16px;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.6);
  cursor: pointer;
  transition: all 0.4s cubic-bezier(0.16, 1, 0.3, 1);
  display: flex;
  flex-direction: column;
  gap: 10px;
  box-shadow: 
    0 2px 4px rgba(0, 0, 0, 0.01),
    0 1px 2px rgba(0, 0, 0, 0.01);
  overflow: hidden;
}

.card-glow {
  position: absolute;
  top: 0; left: 0; right: 0; height: 100%;
  background: linear-gradient(135deg, rgba(76, 100, 226, 0.05), transparent);
  opacity: 0;
  transition: opacity 0.4s;
}

.history-card:hover {
  background: #ffffff;
  border-color: rgba(76, 100, 226, 0.2);
  transform: translateY(-2px);
  box-shadow: 0 12px 24px rgba(76, 100, 226, 0.08);
}

.history-card:hover .card-glow { opacity: 1; }

.history-card.is-favorite {
  border-left: 2px solid #4C64E2;
  background: rgba(255, 255, 255, 0.95);
}

/* Card Typography */
.card-query {
  position: relative;
  font-size: 12.5px;
  font-weight: 500;
  color: #334155;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-summary {
  position: relative;
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  display: flex;
  align-items: center;
  background: rgba(0, 0, 0, 0.02);
  padding: 4px 8px;
  border-radius: 6px;
  width: fit-content;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
  margin-top: -4px;
}

.card-date {
  font-size: 9px;
  font-weight: 600;
  color: #94a3b8;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

/* Card Actions Row */
.card-actions {
  position: relative;
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 4px;
  padding-top: 10px;
  border-top: 1px solid rgba(0, 0, 0, 0.03);
}

.card-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid rgba(76, 100, 226, 0.12);
  background: rgba(76, 100, 226, 0.03);
  color: #5468d5;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.card-btn::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: linear-gradient(135deg, rgba(76, 100, 226, 0.08), transparent);
  opacity: 0;
  transition: opacity 0.3s;
}

.card-btn:hover::before {
  opacity: 1;
}

.card-btn span {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  position: relative;
  z-index: 1;
}

.card-btn :deep(.v-icon) {
  position: relative;
  z-index: 1;
  color: #5468d5;
  filter: drop-shadow(0 1px 2px rgba(76, 100, 226, 0.2));
}

.card-btn:hover {
  background: rgba(76, 100, 226, 0.1);
  border-color: rgba(76, 100, 226, 0.3);
  color: #4C64E2;
  transform: translateY(-1px);
  box-shadow: 0 4px 8px rgba(76, 100, 226, 0.15);
}

.card-btn:hover :deep(.v-icon) {
  color: #4C64E2;
  filter: drop-shadow(0 2px 4px rgba(76, 100, 226, 0.3));
}

.card-btn:active {
  transform: translateY(0);
}

.btn-divider {
  width: 1px;
  height: 12px;
  background: rgba(76, 100, 226, 0.15);
  margin: 0 4px;
}

.fav-btn.active {
  color: #4C64E2;
  background: rgba(76, 100, 226, 0.12);
  border-color: rgba(76, 100, 226, 0.3);
  box-shadow: 0 2px 6px rgba(76, 100, 226, 0.12);
}

.fav-btn.active :deep(.v-icon) {
  color: #4C64E2;
  filter: drop-shadow(0 2px 3px rgba(76, 100, 226, 0.4));
  animation: starPulse 2s ease-in-out infinite;
}

@keyframes starPulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.1); }
}

.exec-btn :deep(.v-icon) {
  color: #5468d5;
}

.exec-btn:hover {
  background: rgba(76, 100, 226, 0.12);
  border-color: rgba(76, 100, 226, 0.4);
  color: #4C64E2;
}

.exec-btn:hover :deep(.v-icon) {
  animation: playBounce 0.6s ease-in-out;
}

@keyframes playBounce {
  0%, 100% { transform: translateX(0); }
  50% { transform: translateX(2px); }
}

/* Empty/Loading States */
.empty-state, .loading-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  color: #94a3b8;
}

.empty-icon-bg {
  width: 56px;
  height: 56px;
  background: rgba(0, 0, 0, 0.02);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 16px;
}

.empty-state p {
  font-size: 13px;
  font-weight: 500;
}

/* Shimmer */
.loading-shimmer {
  width: 100%;
  padding: 0 10px;
}
.shimmer-bar {
  height: 12px;
  background: linear-gradient(90deg, rgba(0,0,0,0.02) 0%, rgba(0,0,0,0.05) 50%, rgba(0,0,0,0.02) 100%);
  background-size: 200% 100%;
  animation: shimmer 1.5s infinite;
  border-radius: 6px;
  margin-bottom: 12px;
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
  padding-top: 16px;
  cursor: pointer;
}

.collapsed-icon-wrapper {
  position: relative;
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  transition: background 0.2s;
}

.collapsed-icon-wrapper:hover {
  background: rgba(0, 0, 0, 0.04);
}

.icon-dim { opacity: 0.4; }

.mini-fav-badge {
  position: absolute;
  top: 4px; right: 4px;
  font-size: 8px;
  font-weight: 900;
  background: #4C64E2;
  color: white;
  min-width: 14px;
  height: 14px;
  padding: 0 4px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 4px rgba(76, 100, 226, 0.4);
}
</style>
