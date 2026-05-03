import { motion } from 'framer-motion';

type ProgressType = 'hunger' | 'happiness' | 'experience';

interface ProgressBarProps {
  type: ProgressType;
  value: number;
  max?: number;
  showLabel?: boolean;
  size?: 'sm' | 'md' | 'lg';
}

const typeConfig: Record<
  ProgressType,
  { color: string; gradient: string; icon: string; label: string }
> = {
  hunger: {
    color: 'bg-primary',
    gradient: 'from-primary to-primary-dark',
    icon: '🍖',
    label: '饱食度',
  },
  happiness: {
    color: 'bg-secondary',
    gradient: 'from-secondary to-yellow-400',
    icon: '💕',
    label: '快乐度',
  },
  experience: {
    color: 'bg-accent',
    gradient: 'from-accent to-teal-400',
    icon: '⭐',
    label: '经验值',
  },
};

const sizeConfig = {
  sm: { height: 'h-2', text: 'text-xs' },
  md: { height: 'h-3', text: 'text-sm' },
  lg: { height: 'h-4', text: 'text-base' },
};

export function ProgressBar({
  type,
  value,
  max = 100,
  showLabel = true,
  size = 'md',
}: ProgressBarProps) {
  const config = typeConfig[type];
  const sizeStyle = sizeConfig[size];
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));

  return (
    <div className="w-full">
      {showLabel && (
        <div className="flex justify-between items-center mb-1">
          <span className={`${sizeStyle.text} text-text-light`}>
            {config.icon} {config.label}
          </span>
          <span className={`${sizeStyle.text} font-mono font-semibold text-text`}>
            {value}/{max}
          </span>
        </div>
      )}
      <div
        className={`w-full ${sizeStyle.height} bg-gray-200 rounded-full overflow-hidden`}
      >
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${percentage}%` }}
          transition={{ duration: 0.4, ease: [0.4, 0, 0.2, 1] }}
          className={`${sizeStyle.height} rounded-full bg-gradient-to-r ${config.gradient}`}
        />
      </div>
    </div>
  );
}
