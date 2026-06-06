<template>
  <div class="layout">
    <Sidebar ref="sidebarRef" />
    <div class="main">
      <ChatWindow />
      <InputBar />
    </div>
    <FileDrawer />

    <Teleport to="body">
      <div v-if="store.authRequired" class="auth-overlay" @click.self="cancel">
        <div class="auth-modal">
          <h3 class="auth-title">需要 API Key</h3>
          <p class="auth-desc">服务端已启用鉴权，请输入 API Key 后重试。</p>
          <input
            ref="keyInput"
            v-model="keyDraft"
            type="password"
            class="auth-input"
            placeholder="API Key"
            autocomplete="off"
            @keyup.enter="submit"
          />
          <div class="auth-actions">
            <button class="auth-btn ghost" @click="cancel">取消</button>
            <button class="auth-btn primary" :disabled="!keyDraft.trim()" @click="submit">保存</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import Sidebar from './components/Sidebar.vue'
import ChatWindow from './components/ChatWindow.vue'
import InputBar from './components/InputBar.vue'
import FileDrawer from './components/FileDrawer.vue'
import { useChatStore } from './stores/chat'

const store = useChatStore()
const keyDraft = ref(store.apiKey || '')
const keyInput = ref(null)
const sidebarRef = ref(null)
const dismissed = ref(false)

watch(() => store.authRequired, async (show) => {
  if (show && !dismissed.value) {
    keyDraft.value = store.apiKey || ''
    await nextTick()
    keyInput.value?.focus()
  }
})

function submit() {
  const k = keyDraft.value.trim()
  if (!k) return
  store.setApiKey(k)
  dismissed.value = false
  sidebarRef.value?.verify()       // 通知侧边栏验证 key
}

function cancel() {
  store.authRequired = false
  dismissed.value = true       // 不再自动弹窗，可去侧边栏手动设置
}
</script>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  font-size: 14px;
  background: #f7f8fa;
  color: #1a1a1a;
  height: 100vh;
  overflow: hidden;
}

.layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  background: #fff;
}

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #d0d0d0; border-radius: 3px; }

.auth-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,0.35);
  z-index: 200;
  display: flex;
  align-items: center;
  justify-content: center;
}
.auth-modal {
  width: 340px;
  background: #fff;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 10px 40px rgba(0,0,0,0.2);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.auth-title { font-size: 16px; font-weight: 600; color: #1a1a1a; }
.auth-desc { font-size: 13px; color: #666; }
.auth-input {
  padding: 10px 12px;
  border: 1px solid #d0d0d0;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
}
.auth-input:focus { border-color: #4a90d9; }
.auth-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
.auth-btn {
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
}
.auth-btn.ghost { background: #f0f2f5; color: #333; border-color: #d0d0d0; }
.auth-btn.ghost:hover { background: #e4e6ea; }
.auth-btn.primary { background: #4a90d9; color: #fff; }
.auth-btn.primary:hover { background: #3a7ec0; }
.auth-btn.primary:disabled { background: #b8d3ee; cursor: not-allowed; }
</style>
