<script setup lang="ts">
import { computed, defineComponent, h, onMounted, reactive, ref, watch } from 'vue'

type Role = 'user' | 'admin' | 'super_admin'
type SpaceKey = 'personal' | 'shared'
type MenuKey = 'personal' | 'shared' | 'recycle' | 'archive' | 'admin'

interface User {
  id: number
  username: string
  role: Role
}

interface DashboardSnapshot {
  storage: { onlyoffice_url: string }
}

interface TreeNodeRaw {
  id: number
  kind: 'folder' | 'document'
  name: string
  parent: number | null
  permission?: string
  file_type?: string
}

interface TreeResponse {
  roots: TreeNodeRaw[]
  children: Record<string, TreeNodeRaw[]>
}

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').trim()
const auth = reactive({ access: localStorage.getItem('docmaster.access') || '', refresh: localStorage.getItem('docmaster.refresh') || '' })
const user = ref<User | null>(null)
const dashboard = ref<DashboardSnapshot | null>(null)
const loginForm = reactive({ username: '', password: '' })
const loginError = ref('')
const loginSubmitting = ref(false)

const activeMenu = ref<MenuKey>('personal')
const trees = reactive<Record<SpaceKey, TreeResponse>>({
  personal: { roots: [], children: {} },
  shared: { roots: [], children: {} },
})
const treeLoading = ref(false)
const treeError = ref('')
const expandedFolders = ref<Record<string, boolean>>({})
const selectedDoc = ref<{ id: number; space: SpaceKey; name: string; fileType?: string } | null>(null)
const rightPaneError = ref('')
const onlyOfficeHostId = 'onlyoffice-host'
let currentEditor: any = null

const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  space: 'personal' as SpaceKey,
  node: null as TreeNodeRaw | null,
})

const uploadState = reactive({
  visible: false,
  space: 'personal' as SpaceKey,
  folderId: null as number | null,
})
const uploadInput = ref<HTMLInputElement | null>(null)

const isAdminLike = computed(() => user.value?.role === 'admin' || user.value?.role === 'super_admin')
const activeSpace = computed<SpaceKey | null>(() => (activeMenu.value === 'personal' || activeMenu.value === 'shared' ? activeMenu.value : null))

function apiUrl(pathname: string) {
  const base = API_BASE_URL || window.location.origin
  return `${base}${pathname}`
}

function safeJson(text: string) {
  try { return JSON.parse(text) } catch { return text }
}

async function apiRequest<T>(pathname: string, options: { method?: string; body?: any } = {}) {
  const method = options.method || 'GET'
  async function doFetch() {
    const headers: Record<string, string> = {}
    let body: BodyInit | undefined
    if (auth.access) headers.Authorization = `Bearer ${auth.access}`
    if (options.body instanceof FormData) body = options.body
    else if (options.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(options.body) }
    const res = await fetch(apiUrl(pathname), { method, headers, body })
    const text = await res.text()
    const data = text ? safeJson(text) : null
    return { res, text, data }
  }
  async function refreshAccessToken() {
    if (!auth.refresh) return false
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
  }

  for (let i = 0; i < 2; i += 1) {
    const { res, text, data } = await doFetch()
    if (res.status === 401 && i === 0 && await refreshAccessToken()) continue
    if (!res.ok) throw new Error((data && (data.detail || data.message)) || text || '请求失败')
    return data as T
  }
  throw new Error('请求失败')
}

async function loadMe() { user.value = await apiRequest<User>('/api/accounts/me/') }
async function loadDashboard() { dashboard.value = await apiRequest<DashboardSnapshot>('/api/documents/dashboard/') }

async function loadTree(space: SpaceKey) {
  const result = await apiRequest<TreeResponse>(`/api/documents/tree/?space_type=${space}`)
  trees[space] = result
}

async function reloadTrees() {
  treeLoading.value = true
  treeError.value = ''
  try {
    await Promise.all([loadTree('personal'), loadTree('shared')])
  } catch (e) {
    treeError.value = (e as Error).message
  } finally {
    treeLoading.value = false
  }
}

function canManage(space: SpaceKey) {
  if (!user.value) return false
  return space === 'personal' ? true : isAdminLike.value
}

function toggleFolder(node: TreeNodeRaw) {
  const key = `${activeSpace.value}:${node.id}`
  expandedFolders.value[key] = !expandedFolders.value[key]
}

function openDocument(node: TreeNodeRaw, space: SpaceKey) {
  if (node.kind !== 'document') return
  selectedDoc.value = { id: node.id, space, name: node.name, fileType: node.file_type }
  window.location.hash = `#/onlyoffice/${node.id}`
}

function openDocumentInNewWindow() {
  if (!selectedDoc.value) return
  const url = `${window.location.origin}${import.meta.env.BASE_URL}#/onlyoffice/${selectedDoc.value.id}`
  window.open(url, '_blank', 'noopener,noreferrer')
}

function closeContextMenu() { contextMenu.visible = false }

function onNavContextmenu(e: MouseEvent, space: SpaceKey) {
  if (!canManage(space)) return
  e.preventDefault()
  contextMenu.visible = true
  contextMenu.x = e.clientX
  contextMenu.y = e.clientY
  contextMenu.node = null
  contextMenu.space = space
}

function onNodeContextmenu(e: MouseEvent, node: TreeNodeRaw, space: SpaceKey) {
  e.preventDefault()
  contextMenu.visible = true
  contextMenu.x = e.clientX
  contextMenu.y = e.clientY
  contextMenu.node = node
  contextMenu.space = space
}

async function createFolder(parentId?: number) {
  const space = contextMenu.space
  if (!canManage(space)) return
  const name = window.prompt('文件夹命名')
  if (!name?.trim()) return
  await apiRequest('/api/documents/folders/', {
    method: 'POST',
    body: { name: name.trim(), parent: parentId || null, space_type: space },
  })
  closeContextMenu()
  await loadTree(space)
}

async function renameFolder() {
  const node = contextMenu.node
  if (!node || node.kind !== 'folder') return
  const name = window.prompt('请输入新的目录名称', node.name)
  if (!name?.trim() || name.trim() === node.name) return
  await apiRequest(`/api/documents/folders/${node.id}/`, { method: 'PATCH', body: { name: name.trim() } })
  closeContextMenu()
  await loadTree(contextMenu.space)
}

async function deleteFolder() {
  const node = contextMenu.node
  if (!node || node.kind !== 'folder') return
  if (!window.confirm(`确认删除目录 "${node.name}" 吗？`)) return
  await apiRequest(`/api/documents/folders/${node.id}/delete/`, { method: 'POST' })
  closeContextMenu()
  await loadTree(contextMenu.space)
}

async function deleteDocument() {
  const node = contextMenu.node
  if (!node || node.kind !== 'document') return
  if (!window.confirm(`确认删除文件 "${node.name}" 吗？`)) return
  await apiRequest(`/api/documents/documents/${node.id}/delete/`, { method: 'POST' })
  closeContextMenu()
  await loadTree(contextMenu.space)
}

function triggerUpload() {
  if (!contextMenu.node || contextMenu.node.kind !== 'folder') return
  uploadState.visible = true
  uploadState.space = contextMenu.space
  uploadState.folderId = contextMenu.node.id
  closeContextMenu()
  requestAnimationFrame(() => uploadInput.value?.click())
}

async function onFilePicked(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file || !uploadState.folderId) return
  const form = new FormData()
  form.append('file', file)
  form.append('folder', String(uploadState.folderId))
  form.append('space_type', uploadState.space)
  await apiRequest('/api/documents/documents/upload/', { method: 'POST', body: form })
  target.value = ''
  await loadTree(uploadState.space)
}

async function loadOnlyOfficeInline() {
  rightPaneError.value = ''
  if (!selectedDoc.value) return
  try {
    const onlyOfficeUrl = dashboard.value?.storage?.onlyoffice_url
    if (!onlyOfficeUrl) throw new Error('OnlyOffice 地址未配置')
    const scriptUrl = `${onlyOfficeUrl.replace(/\/+$/, '')}/web-apps/apps/api/documents/api.js`
    if (!(window as any).DocsAPI?.DocEditor) {
      await new Promise<void>((resolve, reject) => {
        const el = document.createElement('script')
        el.src = scriptUrl
        el.async = true
        el.onload = () => resolve()
        el.onerror = () => reject(new Error('OnlyOffice 脚本加载失败'))
        document.head.appendChild(el)
      })
    }
    const config = await apiRequest(`/api/documents/documents/${selectedDoc.value.id}/onlyoffice-config/`)
    if (currentEditor?.destroyEditor) currentEditor.destroyEditor()
    currentEditor = new (window as any).DocsAPI.DocEditor(onlyOfficeHostId, config)
  } catch (e) {
    rightPaneError.value = (e as Error).message
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
    await Promise.all([loadDashboard(), reloadTrees()])
  } catch (e) {
    loginError.value = (e as Error).message
  } finally {
    loginSubmitting.value = false
  }
}

async function logout() {
  try { await apiRequest('/api/accounts/logout/', { method: 'POST' }) } catch {}
  auth.access = ''; auth.refresh = ''; user.value = null; selectedDoc.value = null
  localStorage.removeItem('docmaster.access'); localStorage.removeItem('docmaster.refresh')
}

function parseDocIdFromHash(): number | null {
  const m = window.location.hash.match(/^#\/onlyoffice\/(\d+)/)
  return m ? Number(m[1]) : null
}

function syncSelectionFromHash() {
  const id = parseDocIdFromHash()
  if (!id) return
  const allDocs = [...trees.personal.roots, ...Object.values(trees.personal.children).flat(), ...trees.shared.roots, ...Object.values(trees.shared.children).flat()]
    .filter((n) => n.kind === 'document')
  const doc = allDocs.find((n) => n.id === id)
  if (doc) {
    const inPersonal = [...trees.personal.roots, ...Object.values(trees.personal.children).flat()].some((n) => n.kind === 'document' && n.id === id)
    selectedDoc.value = { id: doc.id, name: doc.name, fileType: doc.file_type, space: inPersonal ? 'personal' : 'shared' }
  }
}

async function bootstrap() {
  if (!auth.access) return
  try {
    await Promise.all([loadMe(), loadDashboard(), reloadTrees()])
    syncSelectionFromHash()
  } catch {
    user.value = null
  }
}

watch(selectedDoc, async () => {
  if (selectedDoc.value) await loadOnlyOfficeInline()
}, { deep: true })

onMounted(() => {
  bootstrap()
  document.addEventListener('click', closeContextMenu)
  window.addEventListener('hashchange', syncSelectionFromHash)
})

const TreeNode = defineComponent({
  name: 'TreeNode',
  props: {
    node: { type: Object, required: true },
    childrenMap: { type: Object, required: true },
    space: { type: String, required: true },
    selectedDocId: { type: Number, required: false, default: 0 },
  },
  emits: ['toggle', 'open-doc', 'node-contextmenu'],
  setup(props, { emit }) {
    return () => {
      const n = props.node as TreeNodeRaw
      const isFolder = n.kind === 'folder'
      const children = (props.childrenMap as any)[String(n.id)] || []
      const expanded = (expandedFolders.value as any)[`${props.space}:${n.id}`] ?? false
      return h('div', { class: 'tree-node' }, [
        h('div', {
          class: [
            'tree-line',
            isFolder ? 'folder-line' : 'document-line',
            isFolder && children.length ? 'has-children' : '',
            n.kind === 'document' && props.selectedDocId === n.id ? 'active' : '',
          ],
          onClick: () => (isFolder ? emit('toggle', n) : emit('open-doc', n, props.space)),
          onContextmenu: (e: MouseEvent) => emit('node-contextmenu', e, n, props.space),
        }, [
          h('span', { class: 'arrow' }, isFolder && children.length ? (expanded ? '▾' : '▸') : ''),
          h('span', { class: 'node-icon' }, isFolder ? '📁' : '📄'),
          h('span', { class: 'name' }, n.name),
        ]),
        isFolder && expanded
          ? h('div', { class: 'tree-children' }, children.map((c: any) =>
            h(TreeNode as any, {
              node: c, childrenMap: props.childrenMap, space: props.space, selectedDocId: props.selectedDocId,
              onToggle: (item: TreeNodeRaw) => emit('toggle', item),
              onOpenDoc: (item: TreeNodeRaw, s: SpaceKey) => emit('open-doc', item, s),
              onNodeContextmenu: (evt: MouseEvent, item: TreeNodeRaw, s: SpaceKey) => emit('node-contextmenu', evt, item, s),
            })))
          : null,
      ])
    }
  },
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <div class="brand">DocMaster</div>
      <div class="spacer" />
      <template v-if="user">
        <div class="user">{{ user.username }} ({{ user.role }})</div>
        <button class="btn" @click="logout">退出</button>
      </template>
    </header>

    <main class="content">
      <section v-if="!user" class="login-card">
        <h2>登录</h2>
        <input v-model="loginForm.username" placeholder="用户名" />
        <input v-model="loginForm.password" type="password" placeholder="密码" @keyup.enter="login" />
        <div v-if="loginError" class="error">{{ loginError }}</div>
        <button class="btn primary" :disabled="loginSubmitting" @click="login">{{ loginSubmitting ? '登录中…' : '登录' }}</button>
      </section>

      <section v-else class="workbench">
        <aside class="left-nav">
          <button
            class="nav-item"
            :class="{ active: activeMenu === 'personal' }"
            @click="activeMenu = 'personal'"
            @contextmenu="onNavContextmenu($event, 'personal')"
          >
            个人文档库
          </button>
          <div v-if="activeMenu === 'personal' && (treeLoading || treeError || trees.personal.roots.length)" class="nav-tree">
            <div v-if="treeError" class="nav-error">{{ treeError }}</div>
            <div v-else-if="treeLoading" class="nav-empty">目录加载中...</div>
            <TreeNode
              v-for="root in trees.personal.roots"
              :key="`personal-${root.kind}-${root.id}`"
              :node="root"
              :children-map="trees.personal.children"
              space="personal"
              :selected-doc-id="selectedDoc?.id || 0"
              @toggle="toggleFolder"
              @open-doc="openDocument"
              @node-contextmenu="onNodeContextmenu"
            />
          </div>

          <button
            class="nav-item"
            :class="{ active: activeMenu === 'shared' }"
            @click="activeMenu = 'shared'"
            @contextmenu="onNavContextmenu($event, 'shared')"
          >
            共享空间
          </button>
          <div v-if="activeMenu === 'shared' && (treeLoading || treeError || trees.shared.roots.length)" class="nav-tree">
            <div v-if="treeError" class="nav-error">{{ treeError }}</div>
            <div v-else-if="treeLoading" class="nav-empty">目录加载中...</div>
            <TreeNode
              v-for="root in trees.shared.roots"
              :key="`shared-${root.kind}-${root.id}`"
              :node="root"
              :children-map="trees.shared.children"
              space="shared"
              :selected-doc-id="selectedDoc?.id || 0"
              @toggle="toggleFolder"
              @open-doc="openDocument"
              @node-contextmenu="onNodeContextmenu"
            />
          </div>

          <button class="nav-item" :class="{ active: activeMenu === 'recycle' }" @click="activeMenu = 'recycle'">回收站</button>
          <div v-if="activeMenu === 'recycle'" class="nav-placeholder">回收站列表后续接入。</div>
          <button class="nav-item muted" :class="{ active: activeMenu === 'archive' }" @click="activeMenu = 'archive'">归档视图（占位）</button>
          <div v-if="activeMenu === 'archive'" class="nav-placeholder">该模块首版暂为占位。</div>
          <button class="nav-item muted" :class="{ active: activeMenu === 'admin' }" @click="activeMenu = 'admin'">管理中心（占位）</button>
          <div v-if="activeMenu === 'admin'" class="nav-placeholder">该模块首版暂为占位。</div>
        </aside>

        <section class="editor-pane">
          <div class="pane-header">
            <strong>{{ selectedDoc ? selectedDoc.name : '欢迎使用 DocMaster' }}</strong>
            <button v-if="selectedDoc" class="btn small" @click="openDocumentInNewWindow">新窗口打开</button>
          </div>
          <div v-if="rightPaneError" class="error">{{ rightPaneError }}</div>
          <div v-if="!selectedDoc" class="welcome">请选择左侧文件在此处打开（OnlyOffice 内嵌）。</div>
          <div v-else-if="!['word', 'excel', 'ppt'].includes(selectedDoc.fileType || '')" class="welcome">该文件类型当前不支持在线编辑。</div>
          <div v-else :id="onlyOfficeHostId" class="onlyoffice-host" />
        </section>
      </section>
    </main>

    <div
      v-if="contextMenu.visible && canManage(contextMenu.space)"
      class="context-menu"
      :style="{ left: `${contextMenu.x}px`, top: `${contextMenu.y}px` }"
    >
      <template v-if="!contextMenu.node">
        <button class="menu-item" @click="createFolder()">新建文件夹</button>
      </template>
      <template v-else-if="contextMenu.node.kind === 'folder'">
        <button class="menu-item" @click="createFolder(contextMenu.node.id)">新建文件夹</button>
        <button class="menu-item" @click="triggerUpload">上传文件</button>
        <button class="menu-item" @click="renameFolder">重命名</button>
        <button class="menu-item danger" @click="deleteFolder">删除文件/文件夹</button>
      </template>
      <template v-else>
        <button class="menu-item danger" @click="deleteDocument">删除文件</button>
      </template>
    </div>

    <input ref="uploadInput" class="hidden-file" type="file" @change="onFilePicked" />
  </div>
</template>

<style scoped>
.shell { min-height: 100vh; background: #e8e0cf; color: #2f2a22; }
.topbar { height: 56px; display: flex; align-items: center; gap: 12px; padding: 0 16px; background: #d9ceb8; border-bottom: 1px solid #c8baa0; }
.brand { font-weight: 700; }
.spacer { flex: 1; }
.content { padding: 10px; }
.login-card { max-width: 380px; margin: 80px auto; display: flex; flex-direction: column; gap: 10px; background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 16px; }
input { padding: 9px 11px; border: 1px solid #cfcfcf; border-radius: 8px; }
.workbench { display: grid; grid-template-columns: 270px 1fr; gap: 10px; height: calc(100vh - 78px); }
.left-nav { background: #4a3524; border-radius: 10px; padding: 10px; display: flex; flex-direction: column; gap: 6px; overflow: auto; }
.nav-item { border: none; text-align: left; background: rgba(255, 255, 255, 0.08); color: #f7ecd8; padding: 10px 12px; border-radius: 8px; cursor: pointer; font-size: 14px; line-height: 20px; font-weight: 600; letter-spacing: .1px; }
.nav-item.active { background: #f4e9d1; color: #4a3524; font-weight: 700; }
.nav-item.muted { opacity: .76; }
.nav-tree { color: #f7ecd8; max-height: 46vh; overflow: auto; padding: 2px 0 8px 6px; border-left: 1px solid rgba(244, 233, 209, .24); }
.nav-empty { color: rgba(247, 236, 216, .72); font-size: 12px; padding: 8px 6px; }
.nav-error { color: #ffd7d7; background: rgba(154, 35, 35, .35); border: 1px solid rgba(255, 180, 180, .35); border-radius: 8px; padding: 8px; font-size: 12px; word-break: break-word; }
.nav-placeholder { color: rgba(247, 236, 216, .76); font-size: 12px; padding: 2px 8px 8px; }
.editor-pane { background: #f5efe2; border: 1px solid #d6c8ac; border-radius: 10px; padding: 10px; display: flex; flex-direction: column; overflow: hidden; }
.pane-header { display: flex; align-items: center; gap: 8px; justify-content: space-between; margin-bottom: 10px; }
.tree-node { position: relative; }
.tree-line { min-height: 28px; padding: 4px 8px 4px 4px; border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 5px; font-size: 12px; line-height: 18px; color: rgba(247, 236, 216, .9); }
.tree-line:hover { background: rgba(255, 255, 255, .10); }
.tree-line.active { background: #f4e9d1; color: #4a3524; font-weight: 700; }
.folder-line { font-weight: 600; }
.document-line { font-weight: 400; color: rgba(247, 236, 216, .82); }
.arrow { width: 12px; flex: 0 0 12px; color: rgba(247, 236, 216, .68); }
.node-icon { width: 16px; flex: 0 0 16px; opacity: .9; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tree-children { position: relative; margin-left: 13px; padding-left: 13px; }
.tree-children::before { content: ''; position: absolute; left: 4px; top: 2px; bottom: 6px; width: 1px; background: rgba(244, 233, 209, .28); }
.btn { border: 1px solid #bca988; border-radius: 8px; background: #f5e8d1; padding: 6px 10px; cursor: pointer; }
.btn.primary { background: #7c5cff; color: #fff; border-color: #7c5cff; }
.btn.small { padding: 4px 8px; font-size: 12px; }
.error { color: #9a2323; background: #ffe7e7; border: 1px solid #f2b3b3; border-radius: 8px; padding: 8px; }
.empty, .welcome { color: #6f6147; padding: 12px; }
.onlyoffice-host { flex: 1; min-height: 300px; border-radius: 8px; border: 1px solid #d2c4aa; overflow: hidden; background: #fff; }
.context-menu { position: fixed; z-index: 20; min-width: 180px; background: #fff; border: 1px solid #cebda0; border-radius: 8px; box-shadow: 0 8px 20px rgba(0, 0, 0, .15); padding: 6px; display: flex; flex-direction: column; }
.menu-item { text-align: left; border: none; background: transparent; border-radius: 6px; padding: 8px; cursor: pointer; }
.menu-item:hover { background: #f4ead7; }
.menu-item.danger { color: #9a2323; }
.hidden-file { position: fixed; left: -9999px; top: -9999px; }
</style>

