import { Box } from '@mui/material'
import { AlignmentViewer } from './AlignmentViewer'

type Props = { jobId: string }

/** Полноэкранная страница просмотра выравнивания для отдельной вкладки. */
export function FullscreenAlignmentViewer({ jobId }: Props) {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default' }}>
      <AlignmentViewer jobId={jobId} fullScreen />
    </Box>
  )
}
