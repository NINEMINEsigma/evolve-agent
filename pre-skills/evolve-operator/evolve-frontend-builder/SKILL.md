---
name: evolve-frontend-builder
description: "Frontend development guide for evolve-agent. Use when agent needs to (1) modify frontend React components, (2) add new UI features, (3) update TypeScript types, (4) modify styles or themes, (5) fix frontend build errors, or (6) understand the frontend architecture. Triggers on frontend/, .tsx, .ts, .css modifications and React development tasks in evolve-agent contexts."
---

# Evolve Frontend Builder

Complete guide for developing the React + TypeScript + Vite frontend in evolve-agent.

## Frontend Architecture

### Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Framework | React 18 | UI components |
| Language | TypeScript | Type safety |
| Build Tool | Vite | Fast development and production builds |
| Package Manager | pnpm | Dependency management |
| Styling | CSS Modules / Inline | Component styling |

### Directory Structure

```
origin_agent/frontend/
├── src/
│   ├── components/       # React components
│   │   ├── Chat/        # Chat interface
│   │   ├── Tools/       # Tool call displays
│   │   └── common/      # Shared components
│   ├── hooks/           # Custom React hooks
│   ├── contexts/        # React contexts
│   ├── types/           # TypeScript types
│   ├── utils/           # Helper functions
│   ├── App.tsx          # Main application
│   └── main.tsx         # Entry point
├── public/              # Static assets
├── index.html           # HTML template
├── package.json         # Dependencies
├── tsconfig.json        # TypeScript config
└── vite.config.ts       # Vite configuration
```

## Development Workflow

### 1. Making Frontend Changes

All changes go through the evolution system:

```
# Read existing component
read_file: {"path": "fork:frontend/src/components/Chat/Message.tsx"}

# Modify and write back
edit_file: {
  "path": "fork:frontend/src/components/Chat/Message.tsx",
  "old_string": "...",
  "new_string": "..."
}
```

### 2. Build Validation

**CRITICAL**: Always validate frontend before calling `evolve_code`:

```
validate_frontend: {"path": "fork:frontend"}
→ Must return valid: true
→ Then evolve_code: {}
```

The validation runs:
1. `pnpm install` - Install dependencies
2. `pnpm run build` - Production build

### 3. Evolution Flow with Frontend

```
Modify .tsx/.ts/.css files
        │
        ▼
validate_frontend: {}
        │
    ┌───┴───┐
    │       │
   OK     FAIL
    │       │
    ▼       ▼
evolve  Fix errors
_code   and retry
    │
    ▼
Process exits -1
    │
    ▼
Orchestrator swaps
and restarts
```

## Component Development

### Creating New Components

Location: `frontend/src/components/<Category>/<ComponentName>.tsx`

Template:
```tsx
import React from 'react';

interface ComponentNameProps {
  prop1: string;
  prop2?: number;
}

export const ComponentName: React.FC<ComponentNameProps> = ({
  prop1,
  prop2 = 0,
}) => {
  return (
    <div className="component-name">
      <span>{prop1}</span>
      <span>{prop2}</span>
    </div>
  );
};
```

### Component Best Practices

1. **Use TypeScript interfaces** for all props
2. **Export components** explicitly (named exports)
3. **Add CSS classes** for styling hooks
4. **Handle optional props** with defaults
5. **Keep components focused** (single responsibility)

## State Management

### Local State

Use `useState` for component-local state:
```tsx
const [isOpen, setIsOpen] = useState(false);
```

### Global State

Use React Context for global state:
```tsx
// contexts/AppContext.tsx
export const AppContext = createContext<AppContextType | null>(null);

export const AppProvider: React.FC = ({ children }) => {
  const [state, setState] = useState(initialState);
  
  return (
    <AppContext.Provider value={{ state, setState }}>
      {children}
    </AppContext.Provider>
  );
};
```

## TypeScript Guidelines

### Type Definitions

Place shared types in `frontend/src/types/`:
```typescript
// types/api.ts
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result?: unknown;
}
```

### Type Safety Rules

1. **No `any` types** - Use `unknown` if type is truly unknown
2. **Explicit return types** for functions
3. **Null checks** - Handle potentially null values
4. **Discriminated unions** for complex state

## Styling

### CSS Modules

For component-scoped styles:
```css
/* components/Button/Button.module.css */
.button {
  padding: 8px 16px;
  border-radius: 4px;
}

.primary {
  background: #007bff;
  color: white;
}
```

```tsx
import styles from './Button.module.css';

<button className={`${styles.button} ${styles.primary}`}>
  Click me
</button>
```

### Inline Styles

For dynamic styles:
```tsx
<div style={{ 
  color: isActive ? 'green' : 'red',
  fontSize: `${size}px`
}}>
```

## Build Configuration

### package.json Scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "preview": "vite preview"
  }
}
```

### vite.config.ts

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
});
```

## Common Frontend Errors

### TypeScript Errors

```
TS2322: Type 'X' is not assignable to type 'Y'
# Fix: Check interface definitions, ensure types match
```

```
TS2304: Cannot find name 'X'
# Fix: Import missing types or define them
```

### Build Errors

```
Rollup failed to resolve import
# Fix: Check import paths, ensure file exists
```

```
Module not found
# Fix: Run pnpm install, check package.json
```

## Frontend Integration with Agent

### WebSocket Communication

Frontend connects to agent via WebSocket:
```typescript
const ws = new WebSocket('ws://localhost:8765/ws');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Handle messages
};
```

### Displaying Tool Calls

Tool calls are streamed from agent:
```typescript
interface ToolCallMessage {
  type: 'tool_call';
  tool: string;
  args: unknown;
  result?: unknown;
}
```

## Testing Changes

### Manual Testing

1. Make changes to frontend files
2. Run `validate_frontend` to build
3. If build succeeds, call `evolve_code`
4. After restart, test in browser

### Debugging Build Issues

If `validate_frontend` fails:
1. Read stdout/stderr from the result
2. Fix TypeScript errors
3. Check for missing imports
4. Verify build configuration

## Migration Patterns

When refactoring existing components:

1. **Preserve interfaces** - Don't break existing props
2. **Gradual migration** - Update one component at a time
3. **Feature flags** - Use conditionals for new behavior
4. **Validate often** - Build after each change

## Performance Considerations

1. **Memoization** - Use `React.memo`, `useMemo`, `useCallback`
2. **Lazy loading** - Use `React.lazy` for code splitting
3. **Virtualization** - For long lists
4. **Bundle size** - Monitor with `vite-bundle-visualizer`
