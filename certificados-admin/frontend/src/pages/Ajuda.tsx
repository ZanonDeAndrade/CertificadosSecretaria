/**
 * Ajuda — task-oriented reference for the secretariat.
 *
 * Written as answers to the questions actually asked at the counter ("o aluno
 * diz que o certificado não abre"), not as a feature tour. Prose is constrained
 * to a readable measure rather than running the full panel width.
 */
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader, PanelBody } from "../ui/Panel";
import { LinkButton } from "../ui/Button";
import { useAuth } from "../app/AuthContext";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, Role, roleLabel } from "../app/permissions";

interface Topic {
  question: string;
  answer: React.ReactNode;
}

const TOPICS: Topic[] = [
  {
    question: "Como emitir certificados para um evento?",
    answer: (
      <>
        Abra <strong>Emitir certificados</strong>, baixe a planilha modelo e
        preencha uma linha por participante. As colunas <code>nome</code> e{" "}
        <code>carga_horaria</code> são obrigatórias; as demais podem ficar em
        branco. Na Mostra de Iniciação Científica sai um certificado por
        trabalho, válido para todos os autores: preencha <code>autor1</code> a{" "}
        <code>autor8</code> (só <code>autor1</code> é obrigatório),{" "}
        <code>evento</code> e <code>titulo_trabalho</code> (obrigatórios) e, se
        quiser, <code>equipe</code> e <code>carga_horaria</code>. A aba
        “Instruções” do modelo explica cada coluna. Envie a planilha, confira a
        prévia do texto e a lista de linhas com erro, e só então confirme a
        emissão.
      </>
    ),
  },
  {
    question: "O participante diz que o certificado não abre. O que verificar?",
    answer: (
      <>
        Procure o participante no <strong>Histórico</strong> e verifique a
        situação. “Ativo” significa que o download funciona. “Arquivo
        indisponível” indica que o registro existe mas o PDF não foi encontrado
        no armazenamento — nesse caso o certificado precisa ser reemitido.
        “Revogado” significa que o certificado foi cancelado e não pode mais ser
        baixado.
      </>
    ),
  },
  {
    question: "Como revogar um certificado emitido por engano?",
    answer: (
      <>
        No <strong>Histórico</strong>, use a ação <strong>Revogar</strong> na
        linha do participante e informe o motivo. A revogação é permanente: o
        certificado deixa de ser válido na consulta pública e o motivo fica
        registrado na auditoria junto com o seu usuário.
      </>
    ),
  },
  {
    question: "O que o código de validação faz?",
    answer: (
      <>
        É o identificador público do certificado, no formato{" "}
        <code>CERT-ANO-XXXXXX</code>. Qualquer pessoa pode conferir a
        autenticidade na área pública informando esse código, sem precisar de
        login. Ele também aparece no QR Code impresso no certificado.
      </>
    ),
  },
  {
    question: "Como mudar o layout do certificado?",
    answer: (
      <>
        Em <strong>Template do certificado</strong>. Cada alteração cria uma nova
        versão e a versão anterior é preservada — nada é sobrescrito. Uma versão
        só passa a valer para novas emissões depois de ser ativada, e a ativação
        pede confirmação porque afeta todos os certificados emitidos a partir
        daquele momento. A Mostra de Iniciação Científica precisa de uma versão
        própria, sem o nome do participante e com o bloco Autores acima do QR
        Code: escolher esse tipo no editor já monta o ponto de partida. Sem ela,
        a emissão da Mostra fica bloqueada.
      </>
    ),
  },
  {
    question: "Preciso emitir para alguém que já tem certificado do mesmo evento.",
    answer: (
      <>
        O sistema não duplica certificados: ao processar a planilha, linhas que
        já correspondem a um certificado existente são listadas como “já
        existiam” e o código original é mantido. Se o certificado precisa ser
        refeito, revogue o antigo antes de emitir o novo.
      </>
    ),
  },
];

export default function Ajuda() {
  const { user } = useAuth();

  return (
    <>
      <PageHeader
        title="Ajuda"
        description="Respostas para as situações mais comuns do atendimento."
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
        <Panel>
          <PanelHeader title="Perguntas frequentes" />
          <div className="divide-y divide-[color:var(--line)]">
            {TOPICS.map((topic) => (
              <div key={topic.question} className="px-4 py-4 sm:px-5">
                <h3 className="text-[length:var(--text-base)] font-semibold text-[color:var(--ink)]">
                  {topic.question}
                </h3>
                <p className="mt-1.5 max-w-[var(--prose-max)] text-[length:var(--text-sm)] leading-[var(--leading-relaxed)] text-[color:var(--ink-muted)]">
                  {topic.answer}
                </p>
              </div>
            ))}
          </div>
        </Panel>

        <div className="space-y-4">
          <Panel>
            <PanelHeader title="Seu acesso" headingLevel={2} />
            <PanelBody>
              <p className="text-[length:var(--text-sm)] text-[color:var(--ink)]">
                <strong>{user?.username}</strong>
              </p>
              <p className="mt-0.5 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                {roleLabel(user?.role)}
              </p>
              <p className="mt-2 text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                {user?.role && user.role in ROLE_LABELS
                  ? ROLE_DESCRIPTIONS[user.role as Role]
                  : "Perfil não reconhecido pelo sistema. Procure um administrador."}
              </p>
              <LinkButton to="/perfil" variant="secondary" size="sm" className="mt-3">
                Ver detalhes do perfil
              </LinkButton>
            </PanelBody>
          </Panel>

          <Panel>
            <PanelHeader title="Suporte" headingLevel={2} />
            <PanelBody>
              <p className="text-[length:var(--text-sm)] text-[color:var(--ink-muted)]">
                Problemas de acesso, criação de novos usuários e falhas no
                armazenamento são tratados pela equipe de TI da instituição.
              </p>
              {/* No fabricated contact details: the institution fills these in. */}
              <p className="mt-2 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
                Canal de suporte a ser definido pela instituição.
              </p>
            </PanelBody>
          </Panel>
        </div>
      </div>
    </>
  );
}
