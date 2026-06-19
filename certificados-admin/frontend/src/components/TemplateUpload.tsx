import axios from "axios";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  API_BASE_URL,
  TemplateMap,
  getCourses,
  getTemplates,
  uploadTemplate,
} from "../services/api";

const MAX_FILE_BYTES = 5 * 1024 * 1024; // 5 MB

/**
 * Mirrors the Python normalize_course_name() function in template_store.py.
 * Used to reverse-map a stored key (e.g. "administracao") back to its
 * display name (e.g. "Administração") for the templates list.
 */
function normalizeCourse(course: string): string {
  return course
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "") // strip combining diacritics
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "_");
}

function TemplateUpload() {
  const [courseName, setCourseName] = useState("");
  const [courses, setCourses] = useState<string[]>([]);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<TemplateMap>({});
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Reverse map "administracao" → "Administração", built from the live list.
  const keyToCourse = useMemo(
    () => Object.fromEntries(courses.map((c) => [normalizeCourse(c), c])),
    [courses],
  );

  const fetchTemplates = useCallback(async () => {
    setLoadingTemplates(true);
    try {
      const data = await getTemplates();
      setTemplates(data);
    } catch {
      setError("Não foi possível carregar a lista de templates.");
    } finally {
      setLoadingTemplates(false);
    }
  }, []);

  useEffect(() => {
    getCourses()
      .then(setCourses)
      .catch(() => setError("Não foi possível carregar a lista de cursos."));
    fetchTemplates();
  }, [fetchTemplates]);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSuccess("");
    setError("");
    const file = e.target.files?.[0] ?? null;
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".png") && !lowerName.endsWith(".jpg") && !lowerName.endsWith(".jpeg")) {
      setError("Selecione um arquivo PNG ou JPG.");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setError("O arquivo excede o limite de 5 MB.");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      return;
    }
    setSelectedFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSuccess("");
    setError("");

    if (!courseName.trim()) {
      setError("Informe o nome do curso.");
      return;
    }
    if (!selectedFile) {
      setError("Selecione um arquivo PNG.");
      return;
    }

    setLoading(true);
    try {
      const message = await uploadTemplate(courseName.trim(), selectedFile);
      setSuccess(message);
      setCourseName("");
      setSelectedFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await fetchTemplates();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  const courseEntries = Object.entries(templates);

  return (
    <div className="space-y-6">
      {/* Upload form */}
      <div className="rounded-[1.75rem] border border-slate-200/80 bg-white/88 p-6">
        <h2 className="mb-5 text-lg font-semibold text-slate-900">
          Adicionar / substituir template
        </h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="course-name"
                className="text-sm font-medium text-slate-700"
              >
                Curso
              </label>
              <select
                id="course-name"
                value={courseName}
                onChange={(e) => {
                  setSuccess("");
                  setError("");
                  setCourseName(e.target.value);
                }}
                disabled={loading}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm text-slate-900 focus:outline-none focus:ring-2 focus:ring-sky-500 disabled:opacity-50"
              >
                <option value="">Selecione um curso</option>
                {courses.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label
                htmlFor="template-file"
                className="text-sm font-medium text-slate-700"
              >
                Arquivo PNG ou JPG (max. 5 MB)
              </label>
              <input
                id="template-file"
                ref={fileInputRef}
                type="file"
                accept=".png,.jpg,.jpeg,image/png,image/jpeg"
                onChange={handleFileChange}
                disabled={loading}
                className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm text-slate-700 file:mr-3 file:rounded-lg file:border-0 file:bg-sky-50 file:px-3 file:py-1 file:text-sm file:font-medium file:text-sky-700 hover:file:bg-sky-100 disabled:opacity-50"
              />
            </div>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="submit"
              disabled={loading || !courseName.trim() || !selectedFile}
              className="inline-flex items-center justify-center rounded-full bg-slate-950 px-6 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
            >
              {loading ? "Enviando..." : "Salvar template"}
            </button>
            {selectedFile && (
              <span className="text-sm text-slate-500">{selectedFile.name}</span>
            )}
          </div>
        </form>

        {success && (
          <div className="mt-4 rounded-[1.25rem] border border-emerald-200 bg-emerald-50/90 p-4 text-sm font-medium text-emerald-800">
            {success}
          </div>
        )}

        {error && (
          <div className="mt-4 rounded-[1.25rem] border border-rose-200 bg-rose-50/90 p-4 text-sm font-medium text-rose-800">
            {error}
          </div>
        )}
      </div>

      {/* Current templates list */}
      <div className="rounded-[1.75rem] border border-slate-200/80 bg-white/88 p-6">
        <h2 className="mb-5 text-lg font-semibold text-slate-900">
          Templates cadastrados
        </h2>

        {loadingTemplates ? (
          <p className="text-sm text-slate-500">Carregando...</p>
        ) : courseEntries.length === 0 ? (
          <p className="text-sm text-slate-500">
            Nenhum template personalizado cadastrado. O template padrao sera
            usado para todos os cursos.
          </p>
        ) : (
          <ul className="divide-y divide-slate-100">
            {courseEntries.map(([key, relativePath]) => (
              <TemplateRow
                key={key}
                displayName={keyToCourse[key] ?? key.replace(/_/g, " ")}
                relativePath={relativePath}
                onReplace={() => {
                  // Set dropdown to the canonical course name so the select
                  // matches one of the <option> values exactly.
                  setCourseName(keyToCourse[key] ?? "");
                  setSuccess("");
                  setError("");
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-component: a single row in the templates list
// ---------------------------------------------------------------------------

interface TemplateRowProps {
  displayName: string;
  relativePath: string;
  onReplace: () => void;
}

function TemplateRow({ displayName, relativePath, onReplace }: TemplateRowProps) {
  // The backend does not serve user-uploaded templates as static files,
  // so we just show the stored path for reference.
  const storedPath = `${API_BASE_URL.replace(/\/$/, "")}/${relativePath}`;

  return (
    <li className="flex flex-col gap-1 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <p className="text-sm font-semibold text-slate-800">
          {displayName}
        </p>
        <p className="mt-0.5 truncate text-xs text-slate-400">{storedPath}</p>
      </div>
      <button
        type="button"
        onClick={onReplace}
        className="mt-2 self-start rounded-full border border-slate-200 bg-white px-4 py-1.5 text-xs font-medium text-slate-700 transition hover:bg-slate-50 sm:mt-0 sm:self-auto"
      >
        Substituir
      </button>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Error extraction helper
// ---------------------------------------------------------------------------

function extractErrorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (!err.response)
      return `Nao foi possivel conectar ao backend em ${API_BASE_URL}.`;
  }
  return "Nao foi possivel salvar o template. Tente novamente.";
}

export default TemplateUpload;
