export type ElementKey =
  | "name"
  | "event"
  | "course"
  | "date"
  | "institution_name"
  | "issue_location"
  | "issue_line"
  | "signatory_name"
  | "signatory_title"
  | "validation_code"
  | "texto_certificado"
  | "certificate_text"
  | "certificate_type"
  | "equipe"
  | "work_title"
  | "authors"
  | "static"
  | "image"
  | "qr"
  | string;

export type TextAlign = "left" | "center" | "right";

export const KEY_LABELS: Record<string, string> = {
  name: "Nome do participante",
  event: "Evento",
  course: "Curso",
  date: "Data de emissao",
  institution_name: "Nome da instituição",
  issue_location: "Local de emissão",
  issue_line: "Local e data de emissão",
  signatory_name: "Nome do assinante",
  signatory_title: "Cargo do assinante",
  validation_code: "Codigo de validacao",
  texto_certificado: "Corpo do certificado",
  certificate_text: "Corpo do certificado",
  certificate_type: "Tipo do certificado",
  equipe: "Equipe",
  work_title: "Título do trabalho",
  authors: "Autores",
  autor1: "Autor 1",
  autor2: "Autor 2",
  autor3: "Autor 3",
  autor4: "Autor 4",
  autor5: "Autor 5",
  autor6: "Autor 6",
  autor7: "Autor 7",
  autor8: "Autor 8",
  static: "Texto fixo",
  image: "Imagem",
  qr: "QR Code",
};

/** Keys that only make sense on a template for a per-work certificate type. */
export const PER_WORK_KEYS: ElementKey[] = [
  "authors",
  "autor1",
  "autor2",
  "autor3",
  "autor4",
  "autor5",
  "autor6",
  "autor7",
  "autor8",
];

/**
 * Element keys printed from the institutional settings, and which setting
 * feeds each one. Mirrors the backend's `template_fields.SETTING_FOR_KEY`.
 */
export const INSTITUTIONAL_SETTING_FOR_KEY: Record<string, string> = {
  institution_name: "institution_name",
  issue_location: "issue_location",
  issue_line: "issue_location",
  signatory_name: "signatory_name",
  signatory_title: "signatory_title",
};

export const AVAILABLE_FONTS = [
  "Times New Roman",
  "Arial",
  "Georgia",
  "Verdana",
  "Courier New",
] as const;

export type FontFamily = (typeof AVAILABLE_FONTS)[number];

interface BaseTemplateElement {
  id: string;
  type: "text" | "image";
  label: string;
  x: number;
  y: number;
}

export interface TextTemplateElement extends BaseTemplateElement {
  type: "text";
  key: ElementKey;
  fontSize: number;
  fontFamily: FontFamily | string;
  color: string;
  align: TextAlign;
  bold: boolean;
  italic: boolean;
  staticText?: string;
  /**
   * Wrap width in art pixels. Absent: the body and the name wrap at the page
   * bound, every other field is drawn on one line — the historical behaviour.
   */
  width?: number;
  /** Box height in art pixels. Absent: the text's own height. The PDF never clips. */
  height?: number;
  /**
   * Which edge Y positions. "bottom" keeps the base of the block in place and
   * lets it grow upward (the authors block, which must not reach the QR code).
   */
  anchorY?: "top" | "bottom";
}

export interface ImageTemplateElement extends BaseTemplateElement {
  type: "image";
  key: "image";
  src: string;
  width: number;
  height: number;
  opacity?: number;
}

export type TemplateElement = TextTemplateElement | ImageTemplateElement;

export interface TemplateLayout {
  /** Relative URL, e.g. /visual-template-backgrounds/uuid.png */
  background: string;
  image_width: number;
  image_height: number;
  elements: TemplateElement[];
}

export interface VisualTemplate {
  id: string;
  name: string;
  layout: TemplateLayout;
  created_at: string;
  updated_at?: string;
}

/** Mock values shown in the editor canvas preview. */
export const MOCK_DATA: Record<string, string> = {
  name: "Joao Silva",
  event: "Workshop de Inteligencia Artificial",
  course: "Sistemas de Informação",
  date: "27 de abril de 2026",
  institution_name: "Instituição de Ensino",
  issue_location: "São Paulo",
  issue_line: "São Paulo, 27 de abril de 2026.",
  signatory_name: "Helena Martins",
  signatory_title: "Secretária Acadêmica",
  validation_code: "a3f9c1e8b2d4f6a1",
  texto_certificado:
    "participou da Semana de Inovação, promovida pelo Curso de Sistemas de " +
    "Informação, realizada de 10 a 12 de junho de 2026, com carga " +
    "horária total de 12 horas. A atividade contou com palestra ministrada por " +
    "Maria Oliveira.",
  certificate_text:
    "participou da Semana de Inovação, promovida pelo Curso de Sistemas de " +
    "Informação, realizada de 10 a 12 de junho de 2026, com carga " +
    "horária total de 12 horas. A atividade contou com palestra ministrada por " +
    "Maria Oliveira.",
  certificate_type: "Ouvinte",
  equipe: "Equipe Alfa",
  work_title: "Sistema de apoio à decisão para secretarias acadêmicas",
  autor1: "Joao Silva",
  autor2: "Maria Oliveira",
  autor3: "Pedro Santos",
  autor4: "Ana Costa",
  autor5: "Lucas Pereira",
  autor6: "Beatriz Lima",
  autor7: "Rafael Souza",
  autor8: "Carla Dias",
  // Eight authors on purpose: the block is previewed at its tallest.
  authors: [
    "Autor 1: Joao Silva",
    "Autor 2: Maria Oliveira",
    "Autor 3: Pedro Santos",
    "Autor 4: Ana Costa",
    "Autor 5: Lucas Pereira",
    "Autor 6: Beatriz Lima",
    "Autor 7: Rafael Souza",
    "Autor 8: Carla Dias",
  ].join("\n"),
};
