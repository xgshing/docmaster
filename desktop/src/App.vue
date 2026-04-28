<script setup lang="ts">
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue'

type Role = 'user' | 'admin' | 'super_admin'

interface User {
  id: number
  username: string
  role: Role
}

interface DashboardSnapshot {
  storage: {
    onlyoffice_url: string
  }
}

interface SharedTreeNodeRaw {
  id: number
  kind: 'folder' | 'document'
  name: string
  parent: number | null
  permission?: string
  file_type?: string
  file_size?: number
}

interface SharedTreeResponse {
  roots: SharedTreeNodeRaw[]
  children: Record<string, SharedTreeNodeRaw[]>
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').trim()

const auth = reactive({
  access: localStorage.getItem('docmaster.access') || '',
  refresh: localStorage.getItem('docmaster.refresh') || '',
})

const user = ref<User | null>(null)
const dashboard = ref<DashboardSnapshot | null>(null)
const loginForm = reactive({ username: '', password: '' })
const loginError = ref('')
const loginSubmitting = ref(false)

const sharedTree = ref<SharedTreeResponse>({ roots: [], children: {} })
const sharedLoading = ref(false)
const sharedError = ref('')

const active = ref<'shared' | 'admin'>('shared')

function apiUrl(pathname: string) {
  const base = API_BASE_URL || window.location.origin
  return `${base}${pathname}`
}

async function apiRequest<T>(pathname: string, options: { method?: string; body?: any; isForm?: boolean } = {}) {
  const method = options.method || 'GET'

  async function doFetch(withAccessToken: boolean) {
    const headers: Record<string, string> = {}
    let body: BodyInit | undefined

    if (withAccessToken && auth.access) {
      headers.Authorization = `Bearer ${auth.access}`
    }

    if (options.body instanceof FormData) {
      body = options.body
    } else if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
      body = JSON.stringify(options.body)
    }

    const res = await fetch(apiUrl(pathname), { method, headers, body })
    const text = await res.text()
    const data = text ? safeJson(text) : null
    return { res, text, data }
  }

  async function refreshAccessToken() {
    if (!auth.refresh) return false
    try {
      const res = await fetch(apiUrl('/api/accounts/token/refresh/'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh: auth.refresh }),
      })
      const payload = await res.json().catch(() => null)
      if (!res.ok || !payload?.access) return false
      auth.access = String(payload.access)
      localStorage.setItem('docmaster.access', auth.access)
      return true
    } catch {
      return false
    }
  }

  let attempt = 0
  while (attempt < 2) {
    const { res, text, data } = await doFetch(true)

    if (res.status === 401 && attempt === 0) {
      const refreshed = await refreshAccessToken()
      if (refreshed) {
        attempt += 1
        continue
      }
      // Token invalid / kicked.
      auth.access = ''
      auth.refresh = ''
      localStorage.removeItem('docmaster.access')
      localStorage.removeItem('docmaster.refresh')
      user.value = null
    }

    if (!res.ok) {
      const msg = (data && (data.detail || data.message)) || text || '请求失败'
      throw new Error(typeof msg === 'string' ? msg : '请求失败')
    }
    return data as T
  }

  throw new Error('请求失败')
}

function safeJson(text: string) {
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function loadMe() {
  user.value = await apiRequest<User>('/api/accounts/me/')
}

async function loadDashboard() {
  dashboard.value = await apiRequest<DashboardSnapshot>('/api/documents/dashboard/')
}

async function loadSharedTree() {
  sharedLoading.value = true
  sharedError.value = ''
  try {
    sharedTree.value = await apiRequest<SharedTreeResponse>('/api/documents/tree/')
  } catch (e) {
    sharedError.value = (e as Error).message
  } finally {
    sharedLoading.value = false
  }
}

async function login() {
  loginError.value = ''
  if (!loginForm.username.trim() || !loginForm.password.trim()) {
    loginError.value = '请输入用户名和密码'
    return
  }
  loginSubmitting.value = true
  try {
    const result = await apiRequest<{ access: string; refresh: string; user: User }>('/api/accounts/login/', {
      method: 'POST',
      body: { username: loginForm.username.trim(), password: loginForm.password },
    })
    auth.access = result.access
    auth.refresh = result.refresh
    localStorage.setItem('docmaster.access', auth.access)
    localStorage.setItem('docmaster.refresh', auth.refresh)
    user.value = result.user
    loginForm.password = ''
    await Promise.all([loadDashboard(), loadSharedTree()])
  } catch (e) {
    loginError.value = (e as Error).message
  } finally {
    loginSubmitting.value = false
  }
}

async function logout() {
  try {
    await apiRequest('/api/accounts/logout/', { method: 'POST' })
  } catch {
    // ignore
  } finally {
    auth.access = ''
    auth.refresh = ''
    localStorage.removeItem('docmaster.access')
    localStorage.removeItem('docmaster.refresh')
    user.value = null
  }
}

function canEdit(node: SharedTreeNodeRaw) {
  return node.permission === 'edit' || user.value?.role === 'super_admin'
}

async function openOnlyOffice(docId: number) {
  // Open in a new window (full page) to reduce embedding constraints.
  const url = `${window.location.origin}${import.meta.env.BASE_URL}#/onlyoffice/${docId}`
  window.open(url, '_blank', 'noopener,noreferrer')
}

const isOnlyOfficeRoute = computed(() => window.location.hash.startsWith('#/onlyoffice/'))

const TreeNode = defineComponent({
  name: 'TreeNode',
  props: {
    node: { type: Object, required: true },
    childrenMap: { type: Object, required: true },
    canEdit: { type: Function, required: true },
  },
  emits: ['open-onlyoffice'],
  setup(props, { emit }) {
    const expanded = ref(true)
    const children = () => (props.childrenMap as any)[String((props.node as any).id)] || []
    return () => {
      const n: any = props.node
      const isFolder = n.kind === 'folder'
      const label = isFolder ? `📁 ${n.name}` : `📄 ${n.name}`
      const canOpen = !isFolder && (n.file_type === 'word' || n.file_type === 'excel' || n.file_type === 'ppt')
      return h('div', { class: 'tree-node' }, [
        h(
          'div',
          { class: 'tree-line' },
          [
            isFolder
              ? h(
                  'button',
                  { class: 'icon-btn', onClick: () => (expanded.value = !expanded.value), title: '展开/收起' },
                  expanded.value ? '▾' : '▸',
                )
              : h('span', { class: 'icon-placeholder' }, ''),
            h('span', { class: 'tree-label' }, label),
            canOpen
              ? h(
                  'button',
                  { class: 'btn small', onClick: () => emit('open-onlyoffice', n.id) },
                  '在线打开',
                )
              : null,
          ].filter(Boolean),
        ),
        isFolder && expanded.value
          ? h(
              'div',
              { class: 'tree-children' },
              children().map((c: any) =>
                h(TreeNode as any, {
                  node: c,
                  childrenMap: props.childrenMap,
                  canEdit: props.canEdit,
                  onOpenOnlyoffice: (id: number) => emit('open-onlyoffice', id),
                }),
              ),
            )
          : null,
      ])
    }
  },
})

const OnlyOfficePage = defineComponent({
  name: 'OnlyOfficePage',
  props: {
    dashboard: { type: Object, required: false, default: null },
    apiRequest: { type: Function, required: true },
  },
  setup(props) {
    const error = ref('')
    const hostId = 'onlyoffice-host'

    function currentDocId(): number | null {
      const match = window.location.hash.match(/^#\/onlyoffice\/(\d+)/)
      return match ? Number(match[1]) : null
    }

    async function ensureDocsApi(onlyOfficeUrl: string) {
      if ((window as any).DocsAPI?.DocEditor) return
      const scriptUrl = `${onlyOfficeUrl.replace(/\/+$/, '')}/web-apps/apps/api/documents/api.js`
      await new Promise<void>((resolve, reject) => {
        const el = document.createElement('script')
        el.src = scriptUrl
        el.async = true
        el.onload = () => resolve()
        el.onerror = () => reject(new Error('OnlyOffice 脚本加载失败'))
        document.head.appendChild(el)
      })
    }

    onMounted(async () => {
      const docId = currentDocId()
      if (!docId) {
        error.value = '无效的文档 ID'
        return
      }
      try {
        const dash = (props.dashboard as any) || (await (props.apiRequest as any)('/api/documents/dashboard/'))
        const onlyOfficeUrl = dash?.storage?.onlyoffice_url
        if (!onlyOfficeUrl) {
          throw new Error('OnlyOffice 地址未配置')
        }
        const config = await (props.apiRequest as any)(`/api/documents/documents/${docId}/onlyoffice-config/`)
        await ensureDocsApi(onlyOfficeUrl)
        const DocsAPI = (window as any).DocsAPI
        new DocsAPI.DocEditor(hostId, config)
      } catch (e) {
        error.value = (e as Error).message
      }
    })

    return () =>
      h('div', { class: 'onlyoffice-shell' }, [
        h('div', { class: 'onlyoffice-top' }, [
          h('a', { href: `${(import.meta as any).env.BASE_URL}#/`, class: 'link' }, '← 返回'),
          h('div', { class: 'spacer' }),
        ]),
        error.value ? h('div', { class: 'error' }, error.value) : null,
        h('div', { id: hostId, class: 'onlyoffice-host' }),
      ])
  },
})

async function bootstrap() {
  if (!auth.access) {
    return
  }
  try {
    await Promise.all([loadMe(), loadDashboard(), loadSharedTree()])
  } catch {
    user.value = null
  }
}

onMounted(() => {
  bootstrap()
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">DocMaster Web</div>
      <div class="spacer" />
      <template v-if="user">
        <div class="user">
          <span class="user-name">{{ user.username }}</span>
          <span class="user-role">{{ user.role }}</span>
        </div>
        <button class="btn" @click="logout">退出</button>
      </template>
    </header>

    <main class="content">
      <section v-if="!user" class="card login-card">
        <h2>登录</h2>
        <div class="field">
          <label>用户名</label>
          <input v-model="loginForm.username" autocomplete="username" />
        </div>
        <div class="field">
          <label>密码</label>
          <input v-model="loginForm.password" type="password" autocomplete="current-password" @keyup.enter="login" />
        </div>
        <div v-if="loginError" class="error">{{ loginError }}</div>
        <button class="btn primary" :disabled="loginSubmitting" @click="login">
          {{ loginSubmitting ? '登录中…' : '登录' }}
        </button>
        <div class="hint" v-if="!API_BASE_URL">
          需要配置 <code>VITE_API_BASE_URL</code> 指向你的后端（例如 <code>https://doc.yuntuxia.top</code>）。
        </div>
      </section>

      <section v-else-if="isOnlyOfficeRoute" class="onlyoffice-page">
        <OnlyOfficePage :dashboard="dashboard || undefined" :api-request="apiRequest" />
      </section>

      <section v-else class="layout">
        <aside class="sidebar card">
          <button class="tab" :class="{ active: active === 'shared' }" @click="active = 'shared'">共享空间</button>
          <button class="tab" :class="{ active: active === 'admin' }" @click="active = 'admin'">管理</button>
        </aside>

        <section class="main card">
          <template v-if="active === 'shared'">
            <div class="row">
              <h2>共享空间</h2>
              <div class="spacer" />
              <button class="btn" :disabled="sharedLoading" @click="loadSharedTree">
                {{ sharedLoading ? '加载中…' : '刷新' }}
              </button>
            </div>
            <div v-if="sharedError" class="error">{{ sharedError }}</div>
            <div v-if="sharedLoading" class="muted">正在加载目录…</div>

            <div v-else class="tree">
              <TreeNode
                v-for="root in sharedTree.roots"
                :key="`${root.kind}-${root.id}`"
                :node="root"
                :children-map="sharedTree.children"
                :can-edit="canEdit"
                @open-onlyoffice="openOnlyOffice"
              />
            </div>
          </template>

          <template v-else>
            <h2>管理</h2>
            <div class="muted">
              管理模块后续可按需要补齐（用户/分组/权限/回收站等），本次先完成 Web 化 + JWT + OnlyOffice 新窗口。
            </div>
          </template>
        </section>
      </section>
    </main>
  </div>
 </template>

<style scoped>
.shell { min-height: 100vh; background: #0b1020; color: #e6e9f2; }
.topbar { display:flex; align-items:center; gap:12px; padding:14px 18px; border-bottom: 1px solid rgba(255,255,255,.08); }
.brand { font-weight: 700; letter-spacing:.2px; }
.spacer { flex: 1; }
.user { display:flex; gap:10px; align-items:center; opacity:.9; }
.user-role { font-size: 12px; opacity:.75; }
.content { padding: 18px; max-width: 1100px; margin: 0 auto; }
.card { background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.10); border-radius: 14px; padding: 16px; backdrop-filter: blur(10px); }
.login-card { max-width: 420px; margin: 40px auto; display:flex; flex-direction:column; gap:12px; }
.field { display:flex; flex-direction:column; gap:6px; }
input { background: rgba(0,0,0,.35); border: 1px solid rgba(255,255,255,.14); border-radius: 10px; padding: 10px 12px; color: #e6e9f2; outline: none; }
input:focus { border-color: rgba(124,92,255,.7); box-shadow: 0 0 0 3px rgba(124,92,255,.18); }
.btn { background: rgba(255,255,255,.10); border: 1px solid rgba(255,255,255,.14); color: #e6e9f2; border-radius: 10px; padding: 10px 12px; cursor:pointer; }
.btn:hover { background: rgba(255,255,255,.14); }
.btn:disabled { opacity:.6; cursor:not-allowed; }
.btn.primary { background: rgba(124,92,255,.85); border-color: rgba(124,92,255,1); }
.btn.primary:hover { background: rgba(124,92,255,.95); }
.btn.small { padding: 6px 10px; font-size: 12px; border-radius: 9px; }
.error { color: #ffb4b4; background: rgba(255,80,80,.10); border: 1px solid rgba(255,80,80,.20); padding: 10px 12px; border-radius: 10px; }
.muted { opacity:.8; }
.hint { opacity:.8; font-size: 12px; }
.layout { display:grid; grid-template-columns: 220px 1fr; gap: 14px; }
.sidebar { display:flex; flex-direction:column; gap:8px; }
.tab { text-align:left; width:100%; }
.tab.active { background: rgba(124,92,255,.35); border-color: rgba(124,92,255,.55); }
.row { display:flex; align-items:center; gap:12px; margin-bottom: 12px; }
.tree { display:flex; flex-direction:column; gap:6px; }
.tree-node { display:flex; flex-direction:column; }
.tree-line { display:flex; align-items:center; gap:8px; padding: 6px 8px; border-radius: 10px; }
.tree-line:hover { background: rgba(255,255,255,.06); }
.tree-children { padding-left: 18px; display:flex; flex-direction:column; gap:6px; }
.icon-btn { width: 26px; height: 26px; border-radius: 9px; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.12); color:#e6e9f2; cursor:pointer; }
.icon-placeholder { display:inline-block; width: 26px; }
.onlyoffice-shell { height: calc(100vh - 64px); }
.onlyoffice-top { display:flex; align-items:center; gap: 12px; margin-bottom: 10px; }
.onlyoffice-host { height: calc(100vh - 140px); border-radius: 14px; overflow:hidden; border: 1px solid rgba(255,255,255,.10); }
.link { color:#c9c4ff; text-decoration:none; }
.link:hover { text-decoration: underline; }
</style>

