import React from 'react';

/** "Find *calm* in 5 minutes" → the starred words in the highlight colour. */
export const Rich: React.FC<{text: string; highlight: string}> = ({text, highlight}) => (
  <>
    {text.split(/(\*[^*]+\*)/).map((part, i) =>
      part.startsWith('*') && part.endsWith('*') && part.length > 2
        ? <span key={i} style={{color: highlight}}>{part.slice(1, -1)}</span>
        : <React.Fragment key={i}>{part}</React.Fragment>)}
  </>
);
