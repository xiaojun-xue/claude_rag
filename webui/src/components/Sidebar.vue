<template>
  <aside class="sidebar">
    <div class="brand">
      <span class="brand-icon">📚</span>
      <span class="brand-name">知识库助手</span>
    </div>

    <button class="new-btn" @click="store.newSession()">
      <span>＋</span> 新建对话
    </button>

    <div class="session-list">
      <template v-for="(group, label) in grouped" :key="label">
        <div class="group-label">{{ label }}</div>
        <div
          v-for="s in group"
          :key="s.id"
          class="session-item"
          :class="{ active: s.id === store.currentId }"
          @click="store.switchSession(s.id)"
        >
          <span class="session-title">{{ s.title }}</span>
          <button class="del-btn" @click.stop="store.deleteSession(s.id)">×</button>
        </div>
      </template>
    </div>

    <div class="settings">
      <label class="settings-label" for="api-key">API Key</label>
      <input
        id="api-key"
        type="password"
        class="settings-input"
        placeholder="admin 或 readonly key"
        :value="store.apiKey"
        @input="onApiKeyInput"
        @change="onApiKeyChange"
      />
      <div v-if="authStatus" class="auth-status" :class="authStatus">
        {{ authStatus === 'ok' ? '✓ Key 已保存' : '✗ 连接失败，检查 Key' }}
      </div>
    </div>

    <div class="settings">
      <label class="settings-label" for="max-tokens">回答 Token 上限</label>
      <input
        id="max-tokens"
        type="number"
        min="1"
        class="settings-input"
        placeholder="服务端默认"
        :value="store.maxTokens || ''"
        @change="onMaxTokens"
      />
    </div>

    <div class="stats" v-if="stats">
      <span>文档 {{ stats.kb_text }} chunks</span>
      <span>代码 {{ stats.kb_code }} chunks</span>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useChatStore } from '../stores/chat'

const store = useChatStore()
const stats = ref(null)
const authStatus = ref(null)  // null | 'ok' | 'fail'
let verifyTimer = null

async function checkAuth() {
  if (!store.apiKey) {
    authStatus.value = null
    store.authRequired = true        // 没 key → 弹窗提示
    return
  }
  try {
    const r = await store.fetchWithAuth('/api/stats')
    if (r.ok) {
      stats.value = await r.json()
      authStatus.value = 'ok'
    } else if (r.status === 401) {
      authStatus.value = 'fail'
      stats.value = null
      store.authRequired = true       // key 无效 → 弹窗提示
    } else {
      authStatus.value = null
    }
  } catch (_) {
    authStatus.value = null
  }
}

function onApiKeyInput(e) {
  store.setApiKey(e.target.value)       // 只保存，不验证
}

function onApiKeyChange(e) {
  store.setApiKey(e.target.value)
  checkAuth()                           // 失焦时验证
}

function onMaxTokens(e) {
  store.setMaxTokens(e.target.value)
}

// 供弹窗保存后调用
function verify() { clearTimeout(verifyTimer); checkAuth() }
defineExpose({ verify })

// 页面加载时验证
onMounted(() => { checkAuth() })

const grouped = computed(() => {
  const today = new Date(); today.setHours(0,0,0,0)
  const groups = {}
  for (const s of store.sessions) {
    const d = new Date(s.createdAt); d.setHours(0,0,0,0)
    const label = d.getTime() >= today.getTime() ? '今天' : '更早'
    if (!groups[label]) groups[label] = []
    groups[label].push(s)
  }
  return groups
})
</script>

<style scoped>
.sidebar {
  width: 220px;
  min-width: 220px;
  background: #f0f2f5;
  border-right: 1px solid #e4e6ea;
  display: flex;
  flex-direction: column;
  padding: 16px 12px;
  gap: 12px;
  overflow: hidden;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 8px;
  font-weight: 600;
  font-size: 15px;
  color: #1a1a1a;
}
.brand-icon { font-size: 20px; }

.new-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #d0d0d0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: #333;
  transition: background 0.15s;
}
.new-btn:hover { background: #e8eaed; }

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.group-label {
  font-size: 11px;
  color: #888;
  padding: 8px 8px 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.session-item {
  display: flex;
  align-items: center;
  padding: 7px 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.12s;
}
.session-item:hover { background: #e4e6ea; }
.session-item.active { background: #dce0e8; }

.session-title {
  flex: 1;
  font-size: 13px;
  color: #333;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.del-btn {
  visibility: hidden;
  background: none;
  border: none;
  color: #999;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
}
.session-item:hover .del-btn { visibility: visible; }
.del-btn:hover { color: #e55; }

.stats {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px;
  background: #e8eaed;
  border-radius: 6px;
  font-size: 11px;
  color: #666;
}

.settings {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
}
.settings-label {
  font-size: 11px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.settings-input {
  padding: 6px 8px;
  border: 1px solid #d0d0d0;
  border-radius: 6px;
  font-size: 13px;
  background: #fff;
  outline: none;
  width: 100%;
}
.settings-input:focus { border-color: #4a90d9; }

.auth-status {
  font-size: 11px;
  padding: 2px 4px;
}
.auth-status.ok { color: #2a9d4a; }
.auth-status.fail { color: #e55; }
</style>
