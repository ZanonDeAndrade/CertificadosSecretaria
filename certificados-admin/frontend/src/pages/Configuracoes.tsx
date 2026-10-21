import { FormEvent, useEffect, useState } from "react";
import { useAuth } from "../app/AuthContext";
import { useInstitution } from "../app/InstitutionContext";
import { failureMessage, useAsyncData } from "../app/useAsyncData";
import {
  getInstitutionalSettings,
  InstitutionalSettingsInput,
  updateInstitutionalSettings,
} from "../services/api";
import Alert from "../ui/Alert";
import Button from "../ui/Button";
import { Checkbox, Field, TextInput } from "../ui/Field";
import { ErrorState, Skeleton } from "../ui/Feedback";
import PageHeader from "../ui/PageHeader";
import Panel, { PanelBody, PanelHeader, PanelSection } from "../ui/Panel";

const EMPTY: InstitutionalSettingsInput = {
  institution_name: "",
  issue_location: "",
  signatory_name: "",
  signatory_title: "",
  public_url: "",
  retention_days: 0,
  max_batch_rows: 500,
  max_upload_mb: 10,
  secretaria_can_revoke: true,
  secretaria_can_reissue: true,
};

export default function Configuracoes() {
  const { can } = useAuth();
  const institution = useInstitution();
  const state = useAsyncData(getInstitutionalSettings, []);
  const [draft, setDraft] = useState(EMPTY);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    if (!state.data) return;
    const { id: _id, updated_at: _updatedAt, updated_by: _updatedBy, ...input } =
      state.data;
    setDraft(input);
  }, [state.data]);

  const setNumber = (
    key: "retention_days" | "max_batch_rows" | "max_upload_mb",
    value: string,
  ) => setDraft((current) => ({ ...current, [key]: Number(value) || 0 }));

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!can("settings.manage") || saving) return;
    setSaving(true);
    setNotice("");
    setError("");
    try {
      const saved = await updateInstitutionalSettings(draft);
      const { id: _id, updated_at: _updatedAt, updated_by: _updatedBy, ...input } =
        saved;
      setDraft(input);
      setNotice("Configurações institucionais atualizadas e registradas na auditoria.");
      await institution.refresh();
      state.reload();
    } catch (requestError) {
      setError(
        failureMessage(requestError, "Não foi possível salvar as configurações."),
      );
    } finally {
      setSaving(false);
    }
  };

  if (state.initialLoading) {
    return (
      <Panel aria-busy="true" aria-label="Carregando configurações">
        <PanelBody className="space-y-3">
          <Skeleton width="45%" />
          <Skeleton />
          <Skeleton />
        </PanelBody>
      </Panel>
    );
  }

  return (
    <>
      <PageHeader
        title="Configurações institucionais"
        description="Dados de negócio usados na emissão e limites operacionais."
      />

      {state.failure && (
        <Panel>
          <ErrorState
            offline={state.failure === "offline"}
            description={state.error}
            onRetry={state.reload}
          />
        </Panel>
      )}

      {!state.failure && (
        <form onSubmit={submit} className="space-y-4">
          {notice && <Alert tone="ok">{notice}</Alert>}
          {error && <Alert tone="danger">{error}</Alert>}
          {!can("settings.manage") && (
            <Alert tone="info">Esta configuração está disponível somente para leitura.</Alert>
          )}

          <Panel>
            <PanelHeader
              title="Identidade e emissão"
              description="Estes valores substituem textos institucionais fixos no sistema e no certificado."
            />
            <PanelBody className="grid gap-4 sm:grid-cols-2">
              <Field label="Nome da instituição" required>
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.institution_name}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, institution_name: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field
                label="Cidade (local de emissão)"
                hint="Sai como “Cidade, data.” nos certificados. Vazio deixa só a data."
              >
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.issue_location}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, issue_location: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field label="Assinante">
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.signatory_name}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, signatory_name: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field label="Cargo do assinante">
                {(props) => (
                  <TextInput
                    {...props}
                    value={draft.signatory_title}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, signatory_title: event.target.value })
                    }
                  />
                )}
              </Field>
              <Field
                label="URL pública"
                hint="Base HTTPS usada no QR Code e na validação pública."
                className="sm:col-span-2"
              >
                {(props) => (
                  <TextInput
                    {...props}
                    type="url"
                    value={draft.public_url}
                    placeholder="https://certificados.exemplo.br"
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) =>
                      setDraft({ ...draft, public_url: event.target.value })
                    }
                  />
                )}
              </Field>
            </PanelBody>

            <PanelSection className="grid gap-4 sm:grid-cols-3">
              <Field label="Retenção (dias)" hint="0 mantém por prazo indeterminado.">
                {(props) => (
                  <TextInput
                    {...props}
                    type="number"
                    min={0}
                    max={36500}
                    value={draft.retention_days}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) => setNumber("retention_days", event.target.value)}
                  />
                )}
              </Field>
              <Field label="Linhas por lote">
                {(props) => (
                  <TextInput
                    {...props}
                    type="number"
                    min={1}
                    max={10000}
                    value={draft.max_batch_rows}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) => setNumber("max_batch_rows", event.target.value)}
                  />
                )}
              </Field>
              <Field label="Upload máximo (MB)">
                {(props) => (
                  <TextInput
                    {...props}
                    type="number"
                    min={1}
                    max={100}
                    value={draft.max_upload_mb}
                    disabled={!can("settings.manage") || saving}
                    onChange={(event) => setNumber("max_upload_mb", event.target.value)}
                  />
                )}
              </Field>
            </PanelSection>

            <PanelSection>
              <h3 className="mb-2 text-[length:var(--text-sm)] font-semibold text-[color:var(--ink)]">
                Regra institucional da secretaria
              </h3>
              <div className="flex flex-col gap-1 sm:flex-row sm:gap-6">
                <Checkbox
                  label="Pode revogar certificados"
                  checked={draft.secretaria_can_revoke}
                  disabled={!can("settings.manage") || saving}
                  onChange={(event) =>
                    setDraft({ ...draft, secretaria_can_revoke: event.target.checked })
                  }
                />
                <Checkbox
                  label="Pode reemitir certificados"
                  checked={draft.secretaria_can_reissue}
                  disabled={!can("settings.manage") || saving}
                  onChange={(event) =>
                    setDraft({ ...draft, secretaria_can_reissue: event.target.checked })
                  }
                />
              </div>
            </PanelSection>
          </Panel>

          <Alert tone="info" live={false}>
            Segredos, credenciais, tokens e chaves não pertencem a esta área e continuam
            exclusivamente nas variáveis seguras do ambiente.
          </Alert>

          {can("settings.manage") && (
            <Button
              type="submit"
              variant="primary"
              icon="save"
              loading={saving}
              disabled={!draft.institution_name.trim() || draft.max_batch_rows < 1}
            >
              Salvar configurações
            </Button>
          )}
        </form>
      )}
    </>
  );
}
