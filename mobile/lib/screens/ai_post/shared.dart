import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:video_player/video_player.dart';

const navy = Color(0xFF0E1A3A);
const flame = LinearGradient(colors: [Color(0xFFB04DE8), Color(0xFFFF7A2F)]);
const green = Color(0xFF2E9E5B);
const red = Color(0xFFE5484D);

AppBar navyBar(String title, {String? subtitle, List<Widget>? actions}) => AppBar(
      backgroundColor: navy,
      foregroundColor: Colors.white,
      title: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
        if (subtitle != null && subtitle.isNotEmpty) Text(subtitle, style: const TextStyle(fontSize: 11, color: Colors.white70)),
      ]),
      actions: actions,
    );

class GradientButton extends StatelessWidget {
  const GradientButton({super.key, required this.label, required this.onPressed, this.icon, this.busy = false});
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool busy;

  @override
  Widget build(BuildContext context) => Opacity(
        opacity: onPressed == null && !busy ? .5 : 1,
        child: DecoratedBox(
          decoration: BoxDecoration(gradient: flame, borderRadius: BorderRadius.circular(12)),
          child: FilledButton(
            style: FilledButton.styleFrom(backgroundColor: Colors.transparent, shadowColor: Colors.transparent, minimumSize: const Size.fromHeight(50),
                disabledBackgroundColor: Colors.transparent),
            onPressed: busy ? null : onPressed,
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              Flexible(child: Text(label, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600))),
              if (busy) ...[
                const SizedBox(width: 10),
                const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white)),
              ] else if (icon != null) ...[
                const SizedBox(width: 8),
                Icon(icon, color: Colors.white, size: 18),
              ],
            ]),
          ),
        ),
      );
}

String dayLabel(DateTime? d) => d == null ? '' : DateFormat('d MMM').format(d.toLocal());

/// Status line for a post: "Approved for 20 Oct", "Rejected • 17 Oct", …
(String, Color) postStatus(Map<String, dynamic> p) {
  DateTime? at(String k) => p[k] == null ? null : DateTime.parse(p[k] as String);
  switch (p['status']) {
    case 'generating':
      return ('Creating your video…', const Color(0xFFB04DE8));
    case 'in_review':
    case 'draft':
      return ('Waiting for your approval', const Color(0xFFE08A1E));
    case 'scheduled':
    case 'publishing':
      return ('Approved for ${dayLabel(at('scheduled_at'))}', green);
    case 'rejected':
      return ('Rejected • ${dayLabel(at('updated_at'))}', red);
    case 'published':
      return ('Posted ${dayLabel(at('published_at'))}', green);
    case 'gen_failed':
      return ('Couldn’t create the video', red);
    default:
      return ('Not posted — ${(p['last_error'] as String? ?? '').isEmpty ? 'try again' : p['last_error']}', red);
  }
}

/// The post's video (tap to play / pause) or image.
class PostMedia extends StatefulWidget {
  const PostMedia({super.key, required this.post, this.height = 420});
  final Map<String, dynamic> post;
  final double height;

  @override
  State<PostMedia> createState() => _PostMediaState();
}

class _PostMediaState extends State<PostMedia> {
  VideoPlayerController? _video;
  bool _failed = false;

  String get _videoUrl => widget.post['video_url'] as String? ?? '';

  @override
  void initState() {
    super.initState();
    if (widget.post['media_type'] == 'video' && _videoUrl.isNotEmpty) {
      _video = VideoPlayerController.networkUrl(Uri.parse(_videoUrl))
        ..setLooping(true)
        ..initialize().then((_) {
          if (mounted) setState(() {});
        }).catchError((Object _) {
          if (mounted) setState(() => _failed = true);
        });
    }
  }

  @override
  void dispose() {
    _video?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final image = widget.post['image_url'] as String? ?? '';
    final v = _video;
    Widget child;
    if (v != null && v.value.isInitialized && !_failed) {
      child = GestureDetector(
        onTap: () => setState(() => v.value.isPlaying ? v.pause() : v.play()),
        child: Stack(alignment: Alignment.center, children: [
          AspectRatio(aspectRatio: v.value.aspectRatio, child: VideoPlayer(v)),
          if (!v.value.isPlaying) const CircleAvatar(radius: 28, backgroundColor: Colors.black45, child: Icon(Icons.play_arrow, color: Colors.white, size: 34)),
        ]),
      );
    } else if (image.isNotEmpty) {
      child = Stack(alignment: Alignment.center, children: [
        Image.network(image, fit: BoxFit.contain, errorBuilder: (_, _, _) => const Icon(Icons.broken_image_outlined, color: Colors.white54, size: 40)),
        if (v != null && !_failed) const CircularProgressIndicator(color: Colors.white),
      ]);
    } else {
      child = const Icon(Icons.image_outlined, color: Colors.white54, size: 48);
    }
    return Container(
      height: widget.height,
      decoration: BoxDecoration(color: Colors.black, borderRadius: BorderRadius.circular(12)),
      clipBehavior: Clip.antiAlias,
      alignment: Alignment.center,
      child: child,
    );
  }
}

/// Small square thumbnail with a play badge for videos.
class PostThumb extends StatelessWidget {
  const PostThumb(this.post, {super.key, this.size = 72});
  final Map<String, dynamic> post;
  final double size;

  @override
  Widget build(BuildContext context) {
    final image = post['image_url'] as String? ?? '';
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Container(
        width: size,
        height: size,
        color: Colors.black87,
        child: Stack(fit: StackFit.expand, children: [
          if (image.isNotEmpty) Image.network(image, fit: BoxFit.cover, errorBuilder: (_, _, _) => const SizedBox.shrink()),
          if (post['status'] == 'generating') const Center(child: SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))),
          if (post['media_type'] == 'video' && post['status'] != 'generating')
            const Center(child: CircleAvatar(radius: 13, backgroundColor: Colors.black45, child: Icon(Icons.play_arrow, color: Colors.white, size: 18))),
        ]),
      ),
    );
  }
}
