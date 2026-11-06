export const PER_GAME_OPTIONS = [5, 10, 20, 0] as const

interface PerGameSelectProps {
  value: number
  onChange: (value: number) => void
}

export function PerGameSelect({ value, onChange }: PerGameSelectProps) {
  return (
    <label className="select-field per-game-field">
      <span className="per-game-label">Per game</span>
      <select
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label="Maximum streams to show per game"
      >
        {PER_GAME_OPTIONS.map((option) => (
          <option key={option} value={option}>
            {option === 0 ? 'All' : option}
          </option>
        ))}
      </select>
    </label>
  )
}
