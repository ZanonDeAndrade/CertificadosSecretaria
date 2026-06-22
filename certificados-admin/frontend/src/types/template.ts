export type ElementKey =
  | "name"
  | "event"
  | "course"
  | "date"
  | "validation_code"
  | "texto_certificado"
  | "certificate_text"
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
  validation_code: "Codigo de validacao",
  texto_certificado: "Corpo do certificado",
  certificate_text: "Corpo do certificado",
  static: "Texto fixo",
  image: "Imagem",
  qr: "QR Code",
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
  validation_code: "a3f9c1e8b2d4f6a1",
  texto_certificado:
    "participou da Semana de Inovação, promovida pelo Curso de Sistemas de " +
    "Informação da Faculdade, realizada de 10 a 12 de junho de 2026, com carga " +
    "horária total de 12 horas. A atividade contou com palestra ministrada por " +
    "Maria Oliveira.",
  certificate_text:
    "participou da Semana de Inovação, promovida pelo Curso de Sistemas de " +
    "Informação da Faculdade, realizada de 10 a 12 de junho de 2026, com carga " +
    "horária total de 12 horas. A atividade contou com palestra ministrada por " +
    "Maria Oliveira.",
};
