'use strict';

let fileServer='';
const fileTreeCache=new Map();
const fileTreeOpen=new Set();

function resetFileBrowserState(){
  fileServer='';fileAlias='';filePath='';fileTreeCache.clear();fileTreeOpen.clear();
}

function approvedFileRoots(){
  return Object.entries(catalog.roots).filter(([alias])=>folderPermissions(alias).length);
}

function rootsForSelectedContainer(){
  return approvedFileRoots().filter(([,root])=>root.server===fileServer);
}

function treeKey(alias,path){return alias+':'+path}

async function loadFolder(alias,path,refresh=false){
  const key=treeKey(alias,path);
  if(!refresh&&fileTreeCache.has(key))return fileTreeCache.get(key);
  const result=await api('/files/'+encodeURIComponent(alias)+'/list?path='+encodeURIComponent(path));
  fileTreeCache.set(key,result);
  return result;
}

async function filesV2(){
  const roots=approvedFileRoots();
  const serverIds=[...new Set(roots.map(([,root])=>root.server))];
  if(!serverIds.includes(fileServer))fileServer=serverIds[0]||'';
  const selectedRoots=roots.filter(([,root])=>root.server===fileServer);
  if(!selectedRoots.some(([alias])=>alias===fileAlias)){
    fileAlias=selectedRoots[0]?.[0]||'';
    filePath='';
  }
  $('#surface').innerHTML=heading('Container files','Choose a game container, then work inside only the folders assigned to your account.')+(roots.length?`
    <div class="file-console">
      <aside class="file-tree-panel">
        <label for="file-server">Container</label>
        <select id="file-server">${serverIds.map(id=>`<option value="${e(id)}" ${id===fileServer?'selected':''}>${e(catalog.servers[id]?.label||id)}</option>`).join('')}</select>
        <div class="tree-heading"><span>Approved file tree</span><small>Scoped roots only</small></div>
        <nav id="file-tree" class="file-tree" aria-label="Container file tree"></nav>
      </aside>
      <section class="file-workspace">
        <div class="file-workspace-head">
          <div><span class="muted">Current folder</span><div id="file-breadcrumb" class="file-breadcrumb"></div></div>
          <div class="actions">
            <button id="new-folder">New folder</button>
            <label class="button upload-button">Upload files<input id="tree-upload" type="file" multiple aria-label="Upload files"></label>
            <button id="refresh-files">Refresh</button>
          </div>
        </div>
        <div id="file-drop" class="file-drop">Drop files here to upload into the selected folder</div>
        <div id="file-entries"></div>
      </section>
    </div>`:'<div class="card empty">No approved folders are assigned. Ask your administrator for access.</div>');
  if(!roots.length)return;
  $('#file-server').onchange=run(async event=>{
    fileServer=event.target.value;fileAlias='';filePath='';fileTreeCache.clear();fileTreeOpen.clear();await filesV2();
  });
  const permissions=folderPermissions(fileAlias);
  $('#new-folder').disabled=!permissions.includes('upload');
  $('#tree-upload').disabled=!permissions.includes('upload');
  $('#refresh-files').onclick=run(()=>refreshFileBrowser(true));
  $('#new-folder').onclick=()=>newFolderDialog();
  $('#tree-upload').onchange=run(async event=>{await uploadIntoSelectedFolder(event.target.files);event.target.value=''});
  const drop=$('#file-drop');
  drop.classList.toggle('disabled',!permissions.includes('upload'));
  for(const name of ['dragenter','dragover'])drop.addEventListener(name,event=>{event.preventDefault();if(permissions.includes('upload'))drop.classList.add('active')});
  for(const name of ['dragleave','drop'])drop.addEventListener(name,event=>{event.preventDefault();drop.classList.remove('active')});
  drop.addEventListener('drop',run(event=>uploadIntoSelectedFolder(event.dataTransfer.files)));
  await refreshFileBrowser();
}

async function refreshFileBrowser(force=false){
  if(!fileAlias)return;
  const permissions=folderPermissions(fileAlias);
  let listing=null;
  if(permissions.includes('view'))listing=await loadFolder(fileAlias,filePath,force);
  renderFileTree();
  renderFileBreadcrumb();
  renderFileEntries(listing,permissions);
}

function renderFileTree(){
  const roots=rootsForSelectedContainer();
  $('#file-tree').innerHTML=roots.map(([alias,root])=>{
    const selected=alias===fileAlias&&filePath==='';
    return `<div class="tree-root"><button class="tree-row root ${selected?'selected':''}" data-root="${e(alias)}" aria-label="Open root ${e(root.label)}"><span class="tree-icon">▣</span><span>${e(root.label)}</span></button>${alias===fileAlias?renderTreeBranch(alias,''):''}</div>`;
  }).join('');
  bind('[data-root]',async element=>{fileAlias=element.dataset.root;filePath='';fileTreeOpen.add(treeKey(fileAlias,''));await refreshFileBrowser()});
  bind('[data-tree-folder]',async element=>{filePath=element.dataset.treeFolder;fileTreeOpen.add(treeKey(fileAlias,filePath));await loadFolder(fileAlias,filePath);await refreshFileBrowser()});
}

function renderTreeBranch(alias,path){
  const listing=fileTreeCache.get(treeKey(alias,path));
  if(!listing)return '';
  return listing.entries.filter(entry=>entry.directory).map(entry=>{
    const child=join(path,entry.name);
    const selected=alias===fileAlias&&child===filePath;
    return `<div class="tree-branch"><button class="tree-row ${selected?'selected':''}" data-tree-folder="${e(child)}" aria-label="Open folder ${e(entry.name)}"><span class="tree-icon">›</span><span>${e(entry.name)}</span></button>${fileTreeOpen.has(treeKey(alias,child))?renderTreeBranch(alias,child):''}</div>`;
  }).join('');
}

function renderFileBreadcrumb(){
  const root=catalog.roots[fileAlias];
  const segments=filePath?filePath.split('/'):[];
  $('#file-breadcrumb').innerHTML=`<span>${e([root.label,...segments].join(' / '))}</span>${filePath?'<button id="folder-up">Up one level</button>':''}`;
  if($('#folder-up'))$('#folder-up').onclick=run(async()=>{filePath=segments.slice(0,-1).join('/');await refreshFileBrowser()});
}

function renderFileEntries(listing,permissions){
  const target=$('#file-entries');
  if(!permissions.includes('view')){
    const canRead=permissions.includes('read'),canEdit=permissions.includes('edit');
    target.innerHTML=`<div class="empty">Folder listing is not granted. You may use a known relative file path for specifically delegated operations.</div>${canRead||canEdit?`<div class="direct-file card"><div class="section-title"><h2>Known file path</h2><small>Listing remains hidden</small></div><label for="direct-file-path">Relative file path</label><div class="direct-file-row"><input id="direct-file-path" placeholder="folder/file.txt"><div class="actions">${canRead?'<button id="direct-open-file">Open file</button>':''}${canEdit?'<button id="direct-edit-file">Replace file</button>':''}</div></div></div>`:''}`;
    if($('#direct-open-file'))$('#direct-open-file').onclick=run(()=>openFile($('#direct-file-path').value));
    if($('#direct-edit-file'))$('#direct-edit-file').onclick=run(()=>canRead?openFile($('#direct-file-path').value):Promise.resolve(editor($('#direct-file-path').value,'',true)));
    return;
  }
  const entries=listing?.entries||[];
  target.innerHTML=`<div class="table-wrap"><table class="file-table"><thead><tr><th>Name</th><th>Type</th><th>Size</th><th>Modified</th><th>Actions</th></tr></thead><tbody>${entries.map(item=>{
    const path=join(filePath,item.name);
    const actions=item.directory
      ?`<button data-open-folder="${e(path)}" aria-label="Open folder ${e(item.name)}">Open</button>${permissions.includes('delete')?`<button class="danger" data-delete-folder="${e(path)}" data-name="${e(item.name)}" aria-label="Delete folder ${e(item.name)}">Delete</button>`:''}`
      :`${permissions.includes('read')?`<button data-open-file="${e(path)}" aria-label="Open ${e(item.name)}">Open</button><button data-download-file="${e(path)}" aria-label="Download ${e(item.name)}">Download</button>`:''}${permissions.includes('edit')?`<button data-edit-file="${e(path)}" aria-label="Edit ${e(item.name)}">Edit</button>`:''}${permissions.includes('delete')?`<button class="danger" data-delete-file-v2="${e(path)}" data-name="${e(item.name)}" aria-label="Delete ${e(item.name)}">Delete</button>`:''}`;
    return `<tr><td data-label="Name"><span class="file-name"><span aria-hidden="true">${item.directory?'▸':'·'}</span><span>${e(item.name)}</span></span></td><td data-label="Type">${item.directory?'Folder':'File'}</td><td data-label="Size">${item.directory?'—':bytes(item.size)}</td><td data-label="Modified">${new Date(item.modified*1000).toLocaleString()}</td><td data-label="Actions"><div class="actions">${actions||'<small>No actions</small>'}</div></td></tr>`;
  }).join('')}</tbody></table>${entries.length?'':'<div class="empty">This folder is empty.</div>'}</div>`;
  bind('[data-open-folder]',async element=>{filePath=element.dataset.openFolder;fileTreeOpen.add(treeKey(fileAlias,filePath));await loadFolder(fileAlias,filePath);await refreshFileBrowser()});
  bind('[data-open-file]',element=>openFile(element.dataset.openFile));
  bind('[data-download-file]',element=>download(element.dataset.downloadFile));
  bind('[data-edit-file]',element=>permissions.includes('read')?openFile(element.dataset.editFile):editor(element.dataset.editFile,'',true));
  bind('[data-delete-file-v2]',element=>deleteSelectedFile(element.dataset.deleteFileV2,element.dataset.name));
  bind('[data-delete-folder]',element=>deleteSelectedFolder(element.dataset.deleteFolder,element.dataset.name));
}

function newFolderDialog(){
  modal(`<div class="heading"><div><div class="eyebrow">Selected folder</div><h2>Create folder</h2><p class="subtitle">Inside ${e(catalog.roots[fileAlias].label+(filePath?' / '+filePath:''))}</p></div><button data-close>Cancel</button></div><form id="new-folder-form" class="stack"><label>Folder name<input name="name" required maxlength="120" autocomplete="off" placeholder="MyMod"></label><button class="primary" type="submit">Create folder</button></form>`);
  $('#new-folder-form').onsubmit=run(async event=>{
    event.preventDefault();
    const name=event.target.name.value;
    await api('/files/'+encodeURIComponent(fileAlias)+'/directory?path='+encodeURIComponent(join(filePath,name)),'PUT',new Uint8Array(),true);
    close();fileTreeCache.delete(treeKey(fileAlias,filePath));await refreshFileBrowser();notice('Folder created');
  });
}

async function uploadIntoSelectedFolder(files){
  if(!files?.length)return;
  if(!folderPermissions(fileAlias).includes('upload')){notice('Upload permission is not granted',true);return}
  let uploaded=0;
  for(const file of files){
    await api('/files/'+encodeURIComponent(fileAlias)+'/content?path='+encodeURIComponent(join(filePath,file.name)),'PUT',file,true);
    uploaded++;
  }
  fileTreeCache.delete(treeKey(fileAlias,filePath));await refreshFileBrowser();notice(`${uploaded} file${uploaded===1?'':'s'} uploaded`);
}

async function deleteSelectedFile(path,name){
  if(!confirm(`Delete ${name}? A backup will be retained.`))return;
  await api('/files/'+encodeURIComponent(fileAlias)+'/content?path='+encodeURIComponent(path),'DELETE');
  fileTreeCache.delete(treeKey(fileAlias,filePath));await refreshFileBrowser();notice('File deleted; backup retained');
}

async function deleteSelectedFolder(path,name){
  if(!confirm(`Delete empty folder ${name}? Non-empty folders cannot be removed.`))return;
  await api('/files/'+encodeURIComponent(fileAlias)+'/directory?path='+encodeURIComponent(path),'DELETE');
  fileTreeCache.delete(treeKey(fileAlias,filePath));fileTreeCache.delete(treeKey(fileAlias,path));fileTreeOpen.delete(treeKey(fileAlias,path));await refreshFileBrowser();notice('Empty folder deleted');
}
