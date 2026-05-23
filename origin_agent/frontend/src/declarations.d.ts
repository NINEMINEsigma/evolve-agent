declare module "react-syntax-highlighter" {
  import { ComponentType, ReactNode } from "react";

  interface SyntaxHighlighterProps {
    children?: string | string[];
    language?: string;
    style?: Record<string, React.CSSProperties>;
    PreTag?: keyof JSX.IntrinsicElements | ComponentType<{ children: ReactNode; style?: React.CSSProperties }>;
    customStyle?: React.CSSProperties;
    showLineNumbers?: boolean;
    wrapLines?: boolean;
    lineNumberStyle?: React.CSSProperties;
    [key: string]: unknown;
  }

  export const Prism: ComponentType<SyntaxHighlighterProps>;
  export const Light: ComponentType<SyntaxHighlighterProps>;
  export default SyntaxHighlighterProps;
}

declare module "react-syntax-highlighter/dist/esm/styles/prism" {
  import { CSSProperties } from "react";
  const styles: Record<string, CSSProperties>;
  export const oneDark: Record<string, CSSProperties>;
  export const oneLight: Record<string, CSSProperties>;
  export const atomDark: Record<string, CSSProperties>;
  export const coy: Record<string, CSSProperties>;
  export const dark: Record<string, CSSProperties>;
  export const funky: Record<string, CSSProperties>;
  export const okaidia: Record<string, CSSProperties>;
  export const solarizedlight: Record<string, CSSProperties>;
  export const tomorrow: Record<string, CSSProperties>;
  export const twilight: Record<string, CSSProperties>;
  export const vs: Record<string, CSSProperties>;
  export default Record<string, CSSProperties>;
}