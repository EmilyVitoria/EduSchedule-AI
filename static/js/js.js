// EduSchedule AI : interface simples, ligada às rotas Python. //
const $ = seletor => document.querySelector(seletor);
const $$ = seletor => [...document.querySelectorAll(seletor)];
const TURMAS = ['1º ano', '2º ano', '3º ano'];
const DIAS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta'];
const HORAS = ['07:00', '08:00', '09:00', '10:00', '11:00'];
const secoes = {
  painel:['Visão geral','Acompanhe os dados da escola em um só lugar.'],
  alunos:['Alunos','Gerencie os cadastros dos estudantes.'],
  professores:['Professores','Cadastre docentes e distribua disciplinas.'],
  horarios:['Horários','Gere horários respeitando a disponibilidade dos professores.'],
  frequencia:['Frequência','Registre chamadas por aula e acompanhe faltas.'],
  notas:['Notas','Consulte e lance notas bimestrais.'],
  configuracoes:['Configurações','Defina os critérios usados nos cálculos.']
};

let filtroAlunos='ativos', alunos=[], editando=null;
let professores=[], atribuicoes=[], restricoes=[], grade=[];
let chamadaAtual=null, notasAtuais=null, avisoTimer;

// Usamos textContent para mostrar o que foi digitado sem interpretar HTML.
function texto(tag, conteudo, classe='') {
  const el=document.createElement(tag); el.textContent=conteudo; if(classe) el.className=classe; return el;
}

function vazio(el, mensagem='Nenhum registro encontrado.') { el.replaceChildren(texto('p',mensagem,'muted')); }
function botao(rotulo, classe, acao) {
  const b=texto('button',rotulo,classe); b.type='button'; b.addEventListener('click',acao); return b;
}

function notificar(mensagem, falha=false) {
  const el=$('#aviso'); el.textContent=mensagem; el.className=`toast show${falha?' error':''}`;
  clearTimeout(avisoTimer); avisoTimer=setTimeout(()=>el.classList.remove('show'),4500);
}

// Esta função centraliza a comunicação com o Flask e transforma erros em mensagens para o usuário.
async function api(url, opcoes={}) {
  const resposta=await fetch(url,{headers:{'Content-Type':'application/json'},...opcoes});
  let dados;
  try { dados=await resposta.json(); } catch { throw Error('Resposta inválida do servidor.'); }
  if(!resposta.ok) throw Error(dados.erro || 'Falha ao salvar.');
  return dados;
}

async function executar(acao) { try { await acao(); } catch(e) { notificar(e.message,true); } }
function enviar(dados,metodo='POST') { return {method:metodo,body:JSON.stringify(dados)}; }
// Reaproveita a seleção anterior quando a opção ainda existe.

function preencherSelect(el,lista,rotulo='Selecione') {
  const anterior=el.value;
  el.replaceChildren(new Option(rotulo,''));
  lista.forEach(item=>el.add(new Option(item.rotulo,item.valor)));
  if([...el.options].some(o=>o.value===anterior)) el.value=anterior;
  else if(lista.length) el.value=String(lista[0].valor);
}

function escolherTurmas() {
  $$('.select-turmas').forEach(el=>preencherSelect(el,TURMAS.map(t=>({rotulo:t,valor:t}))));
  $$('.select-horarios').forEach(el=>preencherSelect(el,HORAS.map((h,i)=>({rotulo:h,valor:i}))));
}

// O menu troca a seção visível sem recarregar a página inteira.
function abrirSecao(nome) {
  $$('.nav-btn').forEach(b=>b.classList.toggle('active',b.dataset.section===nome));
  $$('.section').forEach(s=>s.classList.toggle('active',s.id===nome));
  $('#page-title').textContent=secoes[nome][0]; $('#page-description').textContent=secoes[nome][1];
  if(nome==='painel') executar(carregarPainel);
  if(nome==='alunos') executar(carregarAlunos);
  if(['professores','horarios','frequencia','notas'].includes(nome)) executar(async()=>{
    await carregarEstrutura(); if(nome==='horarios') await carregarGrade();
  });
  if(nome==='configuracoes') executar(carregarConfiguracoes);
}

$$('.nav-btn').forEach(b=>b.addEventListener('click',()=>abrirSecao(b.dataset.section)));
$('#atalho-alunos').addEventListener('click',()=>abrirSecao('alunos'));

// Busca os números atuais do banco para atualizar os cartões.
async function carregarPainel() {
  const d=await api('/api/painel');
  $('#total-alunos').textContent=d.alunos; $('#total-inativos').textContent=d.inativos;
  $('#total-professores').textContent=d.professores;
  const destino=$('#turmas-painel'); destino.replaceChildren();
  const max=Math.max(1,...Object.values(d.turmas));
  TURMAS.forEach(t=>{
    const bloco=document.createElement('div'), cab=texto('div','','turma-info');
    cab.append(texto('strong',t),texto('span',`${d.turmas[t]||0} aluno(s)`));
    const barra=texto('div','','progress'), preenchimento=document.createElement('span');
    preenchimento.style.width=`${(d.turmas[t]||0)/max*100}%`;
    barra.append(preenchimento); bloco.append(cab,barra); destino.append(bloco);
  });
}

// Alunos: o descadastro não apaga notas nem frequências.
async function carregarAlunos() {
  alunos=await api(`/api/alunos?status=${filtroAlunos}`);
  desenharAlunos();
}

function celula(valor) { return texto('td',valor===null||valor===undefined||valor===''?'—':String(valor)); }
// Monta a tabela a partir dos dados recebidos do servidor.
function desenharAlunos() {
  const destino=$('#lista-alunos'); destino.replaceChildren();
  const busca=$('#busca').value.toLocaleLowerCase('pt-BR');
  const lista=alunos.filter(a=>`${a.nome} ${a.matricula||''}`.toLocaleLowerCase('pt-BR').includes(busca));
  if(!lista.length) {const tr=document.createElement('tr'),td=celula('Nenhum aluno encontrado.'); td.colSpan=5; td.className='empty'; tr.append(td); destino.append(tr); return;}
  lista.forEach(a=>{
    const tr=document.createElement('tr');
    tr.append(celula(a.nome),celula(a.matricula),celula(a.turma));
    const status=document.createElement('td'); status.append(texto('span',a.ativo?'Ativo':'Descadastrado',`pill${a.ativo?'':' inactive'}`)); tr.append(status);
    const acoes=document.createElement('td');
    if(a.ativo) {
      acoes.append(botao('Editar','action-btn',()=>abrirFormulario(a)),
                   botao('Descadastrar','action-btn danger',()=>executar(()=>mudarStatus(a,false))));
    } else acoes.append(botao('Reativar','action-btn',()=>executar(()=>mudarStatus(a,true))));
    tr.append(acoes); destino.append(tr);
  });
}

// Pede confirmação e envia somente o novo status do aluno.
async function mudarStatus(a,ativo) {
  if(!confirm(`Deseja ${ativo?'reativar':'descadastrar'} ${a.nome}? O histórico será preservado.`)) return;
  const r=await api(`/api/alunos/${a.id}/status`,enviar({ativo},'PATCH'));
  notificar(r.mensagem); await carregarAlunos();
}

const modal=$('#modal-aluno'), formAluno=$('#form-aluno');
// O mesmo formulário serve para cadastrar e editar.
function abrirFormulario(aluno=null) {
  editando=aluno?aluno.id:null; formAluno.reset();
  $('#modal-titulo').textContent=aluno?'Editar aluno':'Novo aluno';
  $('#salvar-aluno').textContent=aluno?'Salvar alterações':'Salvar aluno';
  if(aluno) {
    formAluno.elements.namedItem('nome').value=aluno.nome;
    formAluno.elements.namedItem('matricula').value=aluno.matricula||'';
    formAluno.elements.namedItem('turma').value=aluno.turma;
  }
  modal.showModal(); $('#nome').focus();
}

$('#novo-aluno').addEventListener('click',()=>abrirFormulario());
$('#fechar-modal').addEventListener('click',()=>modal.close());
$('#cancelar-modal').addEventListener('click',()=>modal.close());
formAluno.addEventListener('submit',ev=>{
  ev.preventDefault(); executar(async()=>{
    const d=Object.fromEntries(new FormData(formAluno));
    const r=await api(editando?`/api/alunos/${editando}`:'/api/alunos',enviar(d,editando?'PUT':'POST'));
    modal.close(); notificar(r.mensagem); await carregarAlunos();
  });
});

$('#busca').addEventListener('input',desenharAlunos);
$$('.tab').forEach(b=>b.addEventListener('click',()=>{
  filtroAlunos=b.dataset.status;
  $$('.tab').forEach(x=>x.classList.toggle('active',x===b)); executar(carregarAlunos);
}));

// Professores, disciplinas e vínculos.
// Busca docentes, atribuições e bloqueios para atualizar os controles relacionados.
async function carregarEstrutura() {
  [professores,atribuicoes,restricoes]=await Promise.all([
    api('/api/professores'),api('/api/atribuicoes'),api('/api/restricoes')
  ]);
  $$('.select-professores').forEach(el=>preencherSelect(el,professores.map(p=>({valor:p.id,rotulo:p.nome}))));
  desenharProfessores(); desenharAtribuicoes(); desenharRestricoes();
  atualizarDisciplinas();
}

function linhaItem(principal,secundario,rotulo,aoClicar) {
  const linha=texto('div','','item-row'), conteudo=document.createElement('div');
  conteudo.append(texto('strong',principal),texto('small',secundario));
  linha.append(conteudo);
  if(rotulo) linha.append(botao(rotulo,'action-btn danger',aoClicar));
  return linha;
}

function desenharProfessores() {
  const div=$('#lista-professores'); div.replaceChildren();
  if(!professores.length) return vazio(div,'Nenhum professor cadastrado.');
  professores.forEach(p=>div.append(linhaItem(p.nome,'Professor ativo','Descadastrar',()=>executar(async()=>{
    if(!confirm(`Descadastrar ${p.nome}?`)) return;
    const r=await api(`/api/professores/${p.id}`,{method:'DELETE'}); notificar(r.mensagem); await carregarEstrutura();
  }))));
}

// Mostra os vínculos criados, inclusive os que vieram da opção Todas as turmas.
function desenharAtribuicoes() {
  const corpo=$('#lista-atribuicoes'); corpo.replaceChildren();
  atribuicoes.forEach(a=>{
    const tr=document.createElement('tr');
    tr.append(celula(a.turma),celula(a.disciplina),celula(a.professor),celula(a.aulas_semana));
    const td=document.createElement('td'); td.append(botao('Remover','action-btn danger',()=>executar(async()=>{
      if(!confirm(`Remover ${a.disciplina} de ${a.turma}?`)) return;
      const r=await api(`/api/atribuicoes/${a.id}`,{method:'DELETE'});
      notificar(r.mensagem); await carregarEstrutura();
    }))); tr.append(td); corpo.append(tr);
  });
  if(!atribuicoes.length) {const tr=document.createElement('tr'),td=celula('Vincule uma disciplina para começar.');td.colSpan=5;tr.append(td);corpo.append(tr);}
}

// Exibe os horários indisponíveis de cada professor.
function desenharRestricoes() {
  const div=$('#lista-restricoes'); div.replaceChildren();
  if(!restricoes.length) return vazio(div,'Nenhum bloqueio cadastrado.');
  restricoes.forEach(r=>div.append(linhaItem(r.professor,`${DIAS[r.dia]} • ${HORAS[r.horario]}`,'Remover',()=>executar(async()=>{
    const resposta=await api(`/api/restricoes/${r.id}`,{method:'DELETE'});
    notificar(resposta.mensagem); await carregarEstrutura(); await carregarGrade();
  }))));
}

$('#form-professor').addEventListener('submit',ev=>{
  ev.preventDefault(); executar(async()=>{
    const form=ev.currentTarget;
    const r=await api('/api/professores',enviar({nome:form.elements.namedItem('nome').value.trim()}));
    form.reset(); notificar(r.mensagem); await carregarEstrutura();
  });
});

$('#form-atribuicao').addEventListener('submit',ev=>{
  ev.preventDefault(); executar(async()=>{
    const form=ev.currentTarget;
    const r=await api('/api/atribuicoes',enviar(Object.fromEntries(new FormData(form))));
    form.reset(); notificar(r.mensagem); await carregarEstrutura();
  });
});

$('#form-restricao').addEventListener('submit',ev=>{
  ev.preventDefault(); executar(async()=>{
    const r=await api('/api/restricoes',enviar(Object.fromEntries(new FormData(ev.currentTarget))));
    notificar(r.mensagem); await carregarEstrutura(); await carregarGrade();
  });
});

// Horários: nenhum professor pode ocupar duas turmas no mesmo período.
async function carregarGrade() { grade=await api('/api/horarios'); desenharGrade(); }
// Organiza a grade semanal em uma tabela separada para cada turma.
function desenharGrade() {
  const destino=$('#grade-horarios'); destino.replaceChildren();
  const turma=$('#turma-grade').value;
  const table=texto('table','','grade-table');
  const thead=document.createElement('thead'),cab=document.createElement('tr');
  ['Horário',...DIAS].forEach(x=>cab.append(texto('th',x)));
  thead.append(cab); table.append(thead);
  const tbody=document.createElement('tbody');
  HORAS.forEach((h,i)=>{
    const tr=document.createElement('tr'); tr.append(texto('th',h));
    DIAS.forEach((dia,d)=>{
      const td=document.createElement('td');
      const aula=grade.find(a=>a.turma===turma&&a.dia===d&&a.horario===i);
      if(aula) td.append(texto('div',aula.disciplina,'subject'),texto('div',aula.professor,'teacher'));
      else td.append(texto('div','Livre','free'));
      tr.append(td);
    }); tbody.append(tr);
  });
  table.append(tbody);destino.append(table);
}

$('#turma-grade').addEventListener('change',desenharGrade);
$('#excluir-grade').addEventListener('click',()=>executar(async()=>{
  if(!confirm('Excluir o plano de aulas gerado para as três turmas? Os cadastros, notas e chamadas serão preservados.')) return;
  const r=await api('/api/horarios',{method:'DELETE'});
  notificar(r.mensagem);
  await carregarGrade();
}));

$('#gerar-grade').addEventListener('click',()=>executar(async()=>{
  const r=await api('/api/horarios/gerar',{method:'POST'});
  notificar(r.mensagem); await carregarGrade();
}));

// Notas bimestrais e média parcial ou final.
// Mostra apenas as disciplinas da turma selecionada.
function atualizarDisciplinas() {
  [['#turma-notas','#disciplina-notas'],['#turma-frequencia','#disciplina-frequencia']].forEach(([turmaId,discId])=>{
    const turma=$(turmaId).value;
    preencherSelect($(discId),atribuicoes.filter(a=>a.turma===turma).map(a=>({valor:a.id,rotulo:a.disciplina})));
  });
}

$('#turma-notas').addEventListener('change',atualizarDisciplinas);
$('#turma-frequencia').addEventListener('change',atualizarDisciplinas);
$('#buscar-notas').addEventListener('click',()=>executar(carregarNotas));
async function carregarNotas() {
  const turma=$('#turma-notas').value,atrib=$('#disciplina-notas').value;
  if(!atrib) throw Error('Vincule primeiro uma disciplina à turma.');
  notasAtuais={turma,atrib,dados:await api(`/api/notas?turma=${encodeURIComponent(turma)}&atribuicao_id=${atrib}`)};
  desenharNotas();
}

// Apresenta os dados de avaliação retornados pelo backend.
function desenharNotas() {
  const area=$('#tabela-notas'); area.replaceChildren();
  const bimestre=Number($('#bimestre-notas').value), d=notasAtuais.dados;
  $('#aviso-notas').textContent=`Média mínima: ${d.media_minima}. O resultado final aparece após os quatro bimestres.`;
  const tab=document.createElement('table');const head=document.createElement('thead'),tr=document.createElement('tr');
  ['Aluno','1º','2º','3º','4º','Média','Situação',`Editar ${bimestre}º`].forEach(v=>tr.append(texto('th',v)));head.append(tr);tab.append(head);
  const tbody=document.createElement('tbody');
  d.alunos.forEach(a=>{
    const linha=document.createElement('tr');linha.append(celula(a.nome));
    a.notas.forEach(n=>linha.append(celula(n===null?'—':n.toFixed(1))));
    linha.append(celula(a.media===null?'—':a.media.toFixed(2)),celula(a.situacao));
    const td=document.createElement('td'),input=document.createElement('input');
    input.type='number';input.min='0';input.max='10';input.step='0.1';input.className='note-input';input.dataset.alunoId=a.id;
    input.value=a.notas[bimestre-1]===null?'':a.notas[bimestre-1];td.append(input);linha.append(td);tbody.append(linha);
  });tab.append(tbody);area.append(tab);
  $('#salvar-notas').classList.toggle('hidden',!d.alunos.length);
}

$('#bimestre-notas').addEventListener('change',()=>{if(notasAtuais) desenharNotas();});
$('#salvar-notas').addEventListener('click',()=>executar(async()=>{
  if(!notasAtuais) return;
  const notas=$$('#tabela-notas .note-input').map(el=>({aluno_id:Number(el.dataset.alunoId),nota:el.value===''?null:Number(el.value)}));
  const r=await api('/api/notas',enviar({atribuicao_id:notasAtuais.atrib,bimestre:Number($('#bimestre-notas').value),notas},'PUT'));
  notificar(r.mensagem);await carregarNotas();
}));

// Frequência: chamada por horário e por aluno.
const dataHoje=new Date();
$('#data-chamada').value=`${dataHoje.getFullYear()}-${String(dataHoje.getMonth()+1).padStart(2,'0')}-${String(dataHoje.getDate()).padStart(2,'0')}`;
$('#buscar-chamada').addEventListener('click',()=>executar(carregarChamada));
// Consulta a aula da data e do horário escolhidos antes de registrar frequência.
async function carregarChamada() {
  const turma=$('#turma-chamada').value,data=$('#data-chamada').value,horario=$('#horario-chamada').value;
  const dados=await api(`/api/frequencia/chamada?turma=${encodeURIComponent(turma)}&data=${data}&horario=${horario}`);
  chamadaAtual={turma,data,horario,dados};
  $('#descricao-chamada').textContent=`${dados.disciplina} • ${dados.professor}`;
  const div=$('#lista-chamada');div.replaceChildren();
  dados.alunos.forEach(a=>{
    const linha=texto('div','','item-row');linha.append(texto('strong',a.nome));
    const grupo=texto('div','','presence');
    ['Presente','Faltou'].forEach((rotulo,i)=>{
      const label=document.createElement('label'),input=document.createElement('input');
      input.type='radio';input.name=`presenca-${a.id}`;input.value=i===0?'1':'0';
      input.checked=a.presente===(i===0);
      label.append(input,document.createTextNode(rotulo));grupo.append(label);
    });linha.append(grupo);div.append(linha);
  });
  $('#salvar-chamada').classList.remove('hidden');
}

$('#salvar-chamada').addEventListener('click',()=>executar(async()=>{
  if(!chamadaAtual) return;
  const alunos=chamadaAtual.dados.alunos.map(a=>{
    const marcado=document.querySelector(`input[name="presenca-${a.id}"]:checked`);
    if(!marcado) throw Error(`Marque presença ou falta para ${a.nome}.`);
    return {id:a.id,presente:marcado.value==='1'};
  });
  const r=await api('/api/frequencia/chamada',enviar({turma:chamadaAtual.turma,data:chamadaAtual.data,
    horario:chamadaAtual.horario,alunos},'PUT'));
  notificar(r.mensagem); await carregarChamada();
}));

$('#ver-frequencia').addEventListener('click',()=>executar(async()=>{
  const turma=$('#turma-frequencia').value, atrib=$('#disciplina-frequencia').value;
  if(!atrib) throw Error('Selecione uma disciplina.');
  const dados=await api(`/api/frequencia/resumo?turma=${encodeURIComponent(turma)}&atribuicao_id=${atrib}`);
  const div=$('#resumo-frequencia');div.replaceChildren();
  const tab=document.createElement('table'),thead=document.createElement('thead'),tr=document.createElement('tr');
  ['Aluno','Aulas registradas','Faltas','Frequência','Ainda pode faltar','Situação'].forEach(x=>tr.append(texto('th',x)));
  thead.append(tr);tab.append(thead);const tbody=document.createElement('tbody');
  dados.alunos.forEach(a=>{
    const row=document.createElement('tr');
    row.append(celula(a.nome),celula(a.realizadas),celula(a.faltas),celula(a.percentual===null?'—':`${a.percentual}%`),celula(a.faltas_restantes));
    row.append(celula(a.alerta?'Excedeu limite':'Dentro do limite'));tbody.append(row);
  });tab.append(tbody);div.append(tab);
}));

// Parâmetros da escola.
// Carrega os parâmetros atuais para que a direção possa alterá-los na demonstração.
async function carregarConfiguracoes() {
  const d=await api('/api/configuracoes'),f=$('#form-configuracoes');
  Object.keys(d).forEach(k=>{const el=f.elements.namedItem(k);if(el)el.value=d[k];});
}

$('#form-configuracoes').addEventListener('submit',ev=>{
  ev.preventDefault(); executar(async()=>{
    const f=ev.currentTarget;
    const d={media_minima:Number(f.elements.namedItem('media_minima').value),
             frequencia_minima:Number(f.elements.namedItem('frequencia_minima').value),
             semanas_letivas:Number(f.elements.namedItem('semanas_letivas').value)};
    const r=await api('/api/configuracoes',enviar(d,'PUT'));notificar(r.mensagem);
  });
});

// Inicialização da interface.
escolherTurmas();
executar(carregarPainel);
