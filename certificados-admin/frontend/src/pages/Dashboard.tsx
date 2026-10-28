/**
 * Painel — the operational overview the secretariat opens each morning.
 *
 * Every figure here is actionable: each one links to the history screen filtered
 * to exactly the rows it counts, so a number is never a dead end. Counters that
 * would only decorate the page (conversion rates, sparklines, "growth") are
 * deliberately absent — this is a register, not an analytics product.
 *
 * The two attention counters (integridade, arquivo ausente) are shown even when
 * zero, because "zero problems" is itself the information an operator wants
 * confirmed; the rest of the block only appears when it has something to say.
 */
import { Link } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelHeader } from "../ui/Panel";
import Alert from "../ui/Alert";
import Icon, { IconName } from "../ui/Icon";
import { LinkButton } from "../ui/Button";
import StatusBadge, { certificateStatus } from "../ui/StatusBadge";
import { EmptyState, ErrorState, Skeleton } from "../ui/Feedback";
import { Table, TableScroll, Tbody, Td, TdHeader, Th, Thead, Tr } from "../ui/Table";
import { cn } from "../ui/cn";
import { useAuth } from "../app/AuthContext";
import { useAsyncData } from "../app/useAsyncData";
import CertificateSubject from "../components/CertificateSubject";
import {
  AdminCertificate,
  DashboardStats,
  getDashboardStats,
  getRecentCertificates,
} from "../services/api";

interface Metric {
  label: string;
  value: number;
  /** Where this number lives in full. */
  to: string;
  hint: string;
  icon: IconName;
  tone?: "default" | "attention";
}

function MetricTile({ metric, loading }: { metric: Metric; loading: boolean }) {
  const attention = metric.tone === "attention" && metric.value > 0;
  return (
    <li>
      <Link
        to={metric.to}
        className={cn(
          "flex h-full flex-col gap-1 rounded-[var(--radius-md)] border bg-[var(--surface)] p-4",
          "transition-colors duration-[var(--duration-fast)] hover:bg-[var(--surface-sunken)]",
          attention
            ? "border-[color:var(--warn-line)]"
            : "border-[color:var(--line)] hover:border-[color:var(--line-strong)]",
        )}
      >
        <span className="flex items-center gap-2 text-[length:var(--text-sm)] font-medium text-[color:var(--ink-muted)]">
          <Icon
            name={metric.icon}
            size={16}
            className={attention ? "text-[color:var(--warn-fg)]" : "text-[color:var(--brand-600)]"}
          />
          {metric.label}
        </span>

        {loading ? (
          <Skeleton className="mt-1 h-8" width="3.5rem" />
        ) : (
          <span
            className={cn(
              "text-[length:var(--text-3xl)] font-semibold tabular-nums leading-none",
              attention ? "text-[color:var(--warn-fg)]" : "text-[color:var(--ink)]",
            )}
          >
            {metric.value.toLocaleString("pt-BR")}
          </span>
        )}

        <span className="mt-auto pt-1 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
          {metric.hint}
        </span>
      </Link>
    </li>
  );
}

function buildMetrics(stats: DashboardStats | null): Metric[] {
  const s = stats ?? {
    total: 0,
    active: 0,
    revoked: 0,
    failed: 0,
    pending: 0,
    recent: 0,
    recent_days: 30,
    integrity_blocked: 0,
    active_without_file: 0,
  };
  return [
    {
      label: "Certificados emitidos",
      value: s.total,
      to: "/historico",
      hint: "Total no registro, incluindo revogados",
      icon: "certificate",
    },
    {
      label: `Emitidos nos últimos ${s.recent_days} dias`,
      value: s.recent,
      to: "/historico",
      hint: "Volume recente de emissões",
      icon: "clock",
    },
    {
      label: "Revogados",
      value: s.revoked,
      to: "/historico?status=revogado",
      hint: "Não podem mais ser baixados",
      icon: "revoked",
    },
    {
      label: "Falhas na emissão",
      value: s.failed,
      to: "/historico?status=falha",
      hint: "Geração interrompida — exigem nova emissão",
      icon: "error",
      tone: "attention",
    },
  ];
}

export default function Dashboard() {
  const { user, can } = useAuth();

  const statsState = useAsyncData<DashboardStats>(() => getDashboardStats(), []);
  const recentState = useAsyncData<AdminCertificate[]>(
    () => getRecentCertificates(8),
    [],
  );

  const stats = statsState.data;
  const metrics = buildMetrics(stats);

  const integrityIssues =
    (stats?.integrity_blocked ?? 0) + (stats?.active_without_file ?? 0);

  return (
    <>
      <PageHeader
        title={`Bom trabalho, ${user?.username ?? ""}`.trim()}
        description="Situação atual do registro de certificados da secretaria."
        actions={
          can("certificates.issue") ? (
            <LinkButton to="/emitir" variant="primary" icon="issue">
              Emitir certificados
            </LinkButton>
          ) : undefined
        }
      />

      {statsState.error && (
        <Alert tone="danger" className="mb-4">
          {statsState.error}
        </Alert>
      )}

      {/* ── Metrics ─────────────────────────────────────────────────────── */}
      <h2 className="sr-only">Indicadores</h2>
      <ul className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <MetricTile
            key={metric.label}
            metric={metric}
            loading={statsState.initialLoading}
          />
        ))}
      </ul>

      {/* ── Integrity ───────────────────────────────────────────────────── */}
      <Panel className="mb-5">
        <PanelHeader
          title="Integridade do acervo"
          description="Verificação dos arquivos armazenados em relação ao que está registrado no banco."
          actions={
            <LinkButton to="/historico" variant="secondary" size="sm">
              Ver histórico
            </LinkButton>
          }
        />
        <div className="grid gap-px bg-[var(--line)] sm:grid-cols-2">
          <IntegrityRow
            label="Arquivos com divergência de integridade"
            value={stats?.integrity_blocked ?? 0}
            loading={statsState.initialLoading}
            okText="Nenhuma divergência encontrada."
            problemText="O arquivo não corresponde ao registro e o download está bloqueado."
          />
          <IntegrityRow
            label="Certificados ativos sem arquivo"
            value={stats?.active_without_file ?? 0}
            loading={statsState.initialLoading}
            okText="Todos os certificados ativos têm arquivo disponível."
            problemText="Constam como ativos, mas o PDF não foi localizado no armazenamento."
          />
        </div>
        {!statsState.initialLoading && integrityIssues === 0 && (
          <div className="border-t border-[color:var(--line)] px-4 py-3 sm:px-5">
            <p className="flex items-center gap-2 text-[length:var(--text-sm)] text-[color:var(--ok-fg)]">
              <Icon name="success" size={16} />
              Nenhuma pendência de integridade no momento.
            </p>
          </div>
        )}
      </Panel>

      {/* ── Recent activity ─────────────────────────────────────────────── */}
      <Panel>
        <PanelHeader
          title="Emissões recentes"
          description="Últimos certificados registrados no sistema."
          actions={
            <LinkButton to="/historico" variant="secondary" size="sm" iconAfter="arrow-right">
              Ver todos
            </LinkButton>
          }
        />

        {recentState.failure ? (
          <ErrorState
            offline={recentState.failure === "offline"}
            description={recentState.error}
            onRetry={recentState.reload}
          />
        ) : recentState.initialLoading ? (
          <div className="space-y-3 px-4 py-4 sm:px-5">
            {[0, 1, 2, 3].map((row) => (
              <div key={row} className="flex items-center gap-4">
                <Skeleton width="35%" />
                <Skeleton width="20%" />
                <Skeleton width="15%" />
              </div>
            ))}
          </div>
        ) : (recentState.data?.length ?? 0) === 0 ? (
          <EmptyState
            icon="certificate"
            title="Nenhum certificado emitido ainda"
            description="Assim que a primeira planilha for processada, as emissões aparecerão aqui."
            action={
              can("certificates.issue") ? (
                <LinkButton to="/emitir" variant="primary" icon="issue">
                  Emitir certificados
                </LinkButton>
              ) : undefined
            }
          />
        ) : (
          <TableScroll label="Emissões recentes" className="rounded-none border-0">
            <Table caption="Últimos certificados emitidos, do mais recente para o mais antigo">
              <Thead>
                <Tr>
                  <Th>Participante / Trabalho</Th>
                  <Th className="hidden sm:table-cell">Curso ou evento</Th>
                  <Th>Código</Th>
                  <Th>Situação</Th>
                </Tr>
              </Thead>
              <Tbody>
                {recentState.data?.map((cert) => {
                  const status = certificateStatus(cert);
                  return (
                    <Tr key={cert.unique_code}>
                      <TdHeader>
                        <CertificateSubject source={cert} />
                      </TdHeader>
                      <Td className="hidden text-[color:var(--ink-muted)] sm:table-cell">
                        {cert.event_name || cert.course_name || "—"}
                      </Td>
                      <Td mono>{cert.unique_code}</Td>
                      <Td>
                        <StatusBadge tone={status.tone} icon={status.icon}>
                          {status.label}
                        </StatusBadge>
                      </Td>
                    </Tr>
                  );
                })}
              </Tbody>
            </Table>
          </TableScroll>
        )}
      </Panel>
    </>
  );
}

function IntegrityRow({
  label,
  value,
  loading,
  okText,
  problemText,
}: {
  label: string;
  value: number;
  loading: boolean;
  okText: string;
  problemText: string;
}) {
  const ok = value === 0;
  return (
    <div className="bg-[var(--surface)] px-4 py-4 sm:px-5">
      <p className="text-[length:var(--text-sm)] font-medium text-[color:var(--ink)]">
        {label}
      </p>
      <div className="mt-2 flex items-baseline gap-2">
        {loading ? (
          <Skeleton className="h-7" width="2.5rem" />
        ) : (
          <>
            <span
              className={cn(
                "text-[length:var(--text-2xl)] font-semibold tabular-nums",
                ok ? "text-[color:var(--ok-fg)]" : "text-[color:var(--warn-fg)]",
              )}
            >
              {value.toLocaleString("pt-BR")}
            </span>
            <StatusBadge tone={ok ? "ok" : "warn"}>
              {ok ? "Sem pendências" : "Requer atenção"}
            </StatusBadge>
          </>
        )}
      </div>
      <p className="mt-1.5 text-[length:var(--text-xs)] text-[color:var(--ink-subtle)]">
        {ok ? okText : problemText}
      </p>
    </div>
  );
}
