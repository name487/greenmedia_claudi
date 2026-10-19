import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';

import '../api/api_client.dart';
import '../state/session.dart';
import '../widgets/common.dart';
import 'ai_post/shared.dart';

/// A photo or video picked on the phone.
typedef PickedMedia = ({List<int> bytes, String name, bool video});

const _videoExts = {'mp4', 'mov', 'm4v', 'webm', '3gp'};

bool _isVideo(XFile f) => (f.mimeType ?? '').startsWith('video/') || _videoExts.contains(f.name.split('.').last.toLowerCase());

/// Google Media (business owners): photos and videos for the Google profile — Scheduled / Uploaded / Not Posted, and
/// Upload Media from the gallery or the camera, now or one a day.
class GoogleMediaScreen extends StatefulWidget {
  const GoogleMediaScreen({super.key, required this.clientId});
  final int clientId;

  /// Pickers; replaceable in tests.
  static Future<List<PickedMedia>> Function() pickGallery = () async {
    final files = await ImagePicker().pickMultipleMedia(maxWidth: 2400, imageQuality: 90);
    return [for (final f in files) (bytes: await f.readAsBytes(), name: f.name, video: _isVideo(f))];
  };
  static Future<PickedMedia?> Function(bool video) pickCamera = (video) async {
    final picker = ImagePicker();
    final f = video
        ? await picker.pickVideo(source: ImageSource.camera, maxDuration: const Duration(seconds: 30))
        : await picker.pickImage(source: ImageSource.camera, maxWidth: 2400, imageQuality: 90);
    return f == null ? null : (bytes: await f.readAsBytes(), name: f.name, video: video);
  };

  @override
  State<GoogleMediaScreen> createState() => _GoogleMediaScreenState();
}

class _GoogleMediaScreenState extends State<GoogleMediaScreen> {
  String _tab = 'scheduled';
  Map<String, dynamic>? _d;
  List<Map<String, dynamic>>? _categories;
  String? _error;

  ApiClient get _api => context.read<Session>().api;
  String get _base => '/api/clients/${widget.clientId}/google-media';

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Future.wait([_api.get(_base, {'tab': _tab}), if (_categories == null) _api.get('/api/google-media/categories')]);
      if (!mounted) return;
      setState(() {
        _d = r[0] as Map<String, dynamic>;
        if (r.length > 1) _categories = ((r[1] as Map)['categories'] as List).cast<Map<String, dynamic>>();
        _error = null;
      });
    } on ApiException catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _select(String tab) {
    setState(() {
      _tab = tab;
      _d = null;
    });
    _load();
  }

  Future<void> _uploadMenu() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      builder: (s) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              IconButton.outlined(tooltip: 'Close', onPressed: () => Navigator.pop(s), icon: const Icon(Icons.close)),
              const Spacer(),
              OutlinedButton.icon(
                key: const Key('what-to-upload'),
                style: OutlinedButton.styleFrom(foregroundColor: red, side: const BorderSide(color: Color(0xFFF2A3A6)), shape: const StadiumBorder()),
                onPressed: () => Navigator.pop(s, 'help'),
                icon: const Icon(Icons.lightbulb_outline, size: 18),
                label: const Text('What to Upload?'),
              ),
            ]),
            const SizedBox(height: 14),
            GradientButton(key: const Key('open-gallery'), label: 'Open Gallery', icon: Icons.photo_library_outlined, onPressed: () => Navigator.pop(s, 'gallery')),
            const SizedBox(height: 10),
            OutlinedButton.icon(
              key: const Key('open-camera'),
              style: OutlinedButton.styleFrom(foregroundColor: red, side: const BorderSide(color: red), minimumSize: const Size.fromHeight(50),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12))),
              onPressed: () => Navigator.pop(s, 'camera'),
              icon: const Icon(Icons.photo_camera_outlined),
              label: const Text('Open Camera'),
            ),
          ]),
        ),
      ),
    );
    if (!mounted || choice == null) return;
    if (choice == 'help') {
      await showWhatToUpload(context, _categories ?? const []);
      if (mounted) return _uploadMenu();
      return;
    }
    List<PickedMedia> files;
    if (choice == 'gallery') {
      files = await GoogleMediaScreen.pickGallery();
    } else {
      final video = await showModalBottomSheet<bool>(
        context: context,
        builder: (s) => SafeArea(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            ListTile(key: const Key('camera-photo'), leading: const Icon(Icons.photo_camera_outlined), title: const Text('Take a photo'),
                onTap: () => Navigator.pop(s, false)),
            ListTile(key: const Key('camera-video'), leading: const Icon(Icons.videocam_outlined), title: const Text('Record a video'),
                subtitle: const Text('Up to 30 seconds'), onTap: () => Navigator.pop(s, true)),
          ]),
        ),
      );
      if (video == null) return;
      final f = await GoogleMediaScreen.pickCamera(video);
      files = f == null ? [] : [f];
    }
    if (files.isEmpty || !mounted) return;
    final added = await Navigator.push<int>(context,
        MaterialPageRoute(builder: (_) => UploadMediaScreen(clientId: widget.clientId, files: files, categories: _categories ?? const [])));
    if (!mounted || added == null || added == 0) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$added ${added == 1 ? 'item' : 'items'} added — find them under Scheduled')));
    _select('scheduled');
  }

  Future<void> _open(Map<String, dynamic> m) async {
    final d = _d!;
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _MediaSheet(clientId: widget.clientId, item: m, canApprove: d['can_approve'] == true, canUpload: d['can_upload'] == true),
    );
    if (changed == true) _load();
  }

  @override
  Widget build(BuildContext context) {
    final me = context.read<Session>().me!;
    final d = _d;
    final counts = (d?['counts'] as Map?)?.cast<String, dynamic>();
    final items = ((d?['items'] as List?) ?? const []).cast<Map<String, dynamic>>();
    return Scaffold(
      appBar: navyBar('Google Media', subtitle: me.clientName, actions: [
        IconButton(tooltip: 'What to upload?', icon: const Icon(Icons.help_outline), onPressed: () => showWhatToUpload(context, _categories ?? const [])),
      ]),
      body: Column(children: [
        Expanded(
          child: RefreshIndicator(
            onRefresh: _load,
            child: ListView(padding: const EdgeInsets.fromLTRB(12, 12, 12, 16), children: [
              _WhereBar(onTap: () => showWhereItUploads(context, me.clientName ?? '', items)),
              const SizedBox(height: 12),
              _Tabs(value: _tab, onChanged: _select),
              const SizedBox(height: 12),
              if (d == null)
                Padding(padding: const EdgeInsets.all(40), child: Center(child: _error == null ? const CircularProgressIndicator() : Text(_error!)))
              else ...[
                if (d['connected'] != true)
                  Card(
                    color: Colors.orange.shade50,
                    child: const ListTile(
                      leading: Icon(Icons.link_off, color: Colors.orange),
                      title: Text('Google profile not connected'),
                      subtitle: Text('Your media is saved and goes up once your Google Business Profile is connected.'),
                    ),
                  ),
                Text('${counts?[_tab] ?? 0} Media ${const {'scheduled': 'scheduled', 'uploaded': 'uploaded', 'not_posted': 'not posted'}[_tab]}',
                    key: const Key('gm-count'), style: const TextStyle(fontWeight: FontWeight.w700)),
                const SizedBox(height: 10),
                if (items.isEmpty)
                  _Empty(tab: _tab)
                else
                  GridView.builder(
                    shrinkWrap: true,
                    physics: const NeverScrollableScrollPhysics(),
                    gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 3, mainAxisSpacing: 8, crossAxisSpacing: 8, childAspectRatio: .78),
                    itemCount: items.length,
                    itemBuilder: (_, i) => _Tile(item: items[i], onTap: () => _open(items[i])),
                  ),
              ],
            ]),
          ),
        ),
        if (d?['can_upload'] != false)
          SafeArea(
            top: false,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 10),
              child: GradientButton(key: const Key('upload-media'), label: 'Upload Media', icon: Icons.cloud_upload, onPressed: _uploadMenu),
            ),
          ),
      ]),
    );
  }
}

class _WhereBar extends StatelessWidget {
  const _WhereBar({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Material(
        color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: .6),
        borderRadius: BorderRadius.circular(10),
        child: InkWell(
          key: const Key('where-it-uploads'),
          borderRadius: BorderRadius.circular(10),
          onTap: onTap,
          child: const Padding(
            padding: EdgeInsets.symmetric(horizontal: 12, vertical: 12),
            child: Row(children: [
              Expanded(child: Text('Where it will upload?', style: TextStyle(color: Colors.black54))),
              Text('Click here to know', style: TextStyle(color: Color(0xFF1F63C6), fontWeight: FontWeight.w600)),
            ]),
          ),
        ),
      );
}

class _Tabs extends StatelessWidget {
  const _Tabs({required this.value, required this.onChanged});
  final String value;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    const tabs = [('scheduled', 'Scheduled', Icons.event_note), ('uploaded', 'Uploaded', Icons.cloud_upload_outlined), ('not_posted', 'Not Posted', Icons.error_outline)];
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(color: Theme.of(context).colorScheme.surfaceContainerHighest.withValues(alpha: .6), borderRadius: BorderRadius.circular(12)),
      child: Row(children: [
        for (final (key, label, icon) in tabs)
          Expanded(
            child: GestureDetector(
              key: Key('gm-tab-$key'),
              onTap: () => onChanged(key),
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                padding: const EdgeInsets.symmetric(vertical: 9),
                decoration: BoxDecoration(color: value == key ? navy : Colors.transparent, borderRadius: BorderRadius.circular(9)),
                child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Icon(icon, size: 15, color: value == key ? Colors.white : Colors.black54),
                  const SizedBox(width: 5),
                  Flexible(
                    child: Text(label, overflow: TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 12.5, fontWeight: FontWeight.w600, color: value == key ? Colors.white : Colors.black54)),
                  ),
                ]),
              ),
            ),
          ),
      ]),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.tab});
  final String tab;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 56, horizontal: 24),
        child: Column(children: [
          Icon(Icons.calendar_view_month_outlined, size: 64, color: Colors.blue.shade300),
          const SizedBox(height: 14),
          Text(const {'scheduled': 'No Media Scheduled', 'uploaded': 'No Media Uploaded Yet', 'not_posted': 'No Missed Posts'}[tab]!,
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          const Text('Upload now to attract more customers', style: TextStyle(color: Colors.black54)),
        ]),
      );
}

class _Tile extends StatelessWidget {
  const _Tile({required this.item, required this.onTap});
  final Map<String, dynamic> item;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final m = item;
    final when = m['uploaded_at'] ?? m['scheduled_at'];
    final (label, colour) = switch (m['status']) {
      'pending' => ('Needs approval', const Color(0xFFE08A1E)),
      'uploaded' => ('Uploaded ${_date(when)}', green),
      'failed' => ('Not posted', red),
      'publishing' => ('Uploading…', green),
      _ => (_isSoon(when) ? 'Uploading soon' : _date(when), Colors.black87),
    };
    return InkWell(
      key: Key('gm-item-${m['id']}'),
      onTap: onTap,
      borderRadius: BorderRadius.circular(10),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Expanded(
          child: ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Stack(fit: StackFit.expand, children: [
              ColoredBox(color: Colors.black12, child: Image.network(m['thumb_url'] as String, fit: BoxFit.cover,
                  errorBuilder: (_, _, _) => const Icon(Icons.image_outlined, color: Colors.black38))),
              if (m['kind'] == 'video')
                const Center(child: CircleAvatar(radius: 14, backgroundColor: Colors.black45, child: Icon(Icons.play_arrow, color: Colors.white, size: 18))),
            ]),
          ),
        ),
        const SizedBox(height: 4),
        Text(m['category_label'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w600)),
        Text(label, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 11, color: colour)),
      ]),
    );
  }
}

String _date(Object? iso) => iso == null ? '' : DateFormat('d MMM, h:mm a').format(DateTime.parse(iso as String).toLocal());

bool _isSoon(Object? iso) => iso != null && DateTime.parse(iso as String).isBefore(DateTime.now().add(const Duration(minutes: 5)));

/// Tap a tile: the photo or video large, its category and status, and approve / retry / remove where allowed.
class _MediaSheet extends StatefulWidget {
  const _MediaSheet({required this.clientId, required this.item, required this.canApprove, required this.canUpload});
  final int clientId;
  final Map<String, dynamic> item;
  final bool canApprove, canUpload;

  @override
  State<_MediaSheet> createState() => _MediaSheetState();
}

class _MediaSheetState extends State<_MediaSheet> {
  bool _busy = false;

  Future<void> _act(String what) async {
    final base = '/api/clients/${widget.clientId}/google-media/${widget.item['id']}';
    setState(() => _busy = true);
    final ok = await runAction(context, (api) => what == 'remove' ? api.delete(base) : api.post('$base/$what'),
        success: const {'approve': 'Approved', 'retry': 'Trying again', 'remove': 'Removed'}[what]);
    if (!mounted) return;
    setState(() => _busy = false);
    if (ok) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    final m = widget.item;
    final status = m['status'] as String;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          PostMedia(
            post: {'media_type': m['kind'] == 'video' ? 'video' : 'image', 'video_url': m['url'], 'image_url': m['kind'] == 'video' ? m['thumb_url'] : m['url']},
            height: 320,
          ),
          const SizedBox(height: 12),
          Text(m['category_label'] as String, style: Theme.of(context).textTheme.titleMedium),
          const SizedBox(height: 2),
          Text(
            switch (status) {
              'uploaded' => 'On your Google profile since ${_date(m['uploaded_at'])}',
              'pending' => 'Waiting for approval — goes up ${_date(m['scheduled_at'])} or as soon as it’s approved',
              'failed' => 'Not posted: ${m['error']}',
              _ => 'Goes up on your Google profile ${_date(m['scheduled_at'])}',
            },
            key: const Key('gm-status'),
            style: TextStyle(color: status == 'failed' ? red : Colors.black54),
          ),
          const SizedBox(height: 12),
          Row(children: [
            if (widget.canUpload && status != 'uploaded' && status != 'publishing')
              TextButton.icon(key: const Key('gm-remove'), onPressed: _busy ? null : () => _act('remove'), style: TextButton.styleFrom(foregroundColor: red),
                  icon: const Icon(Icons.delete_outline), label: const Text('Remove')),
            const Spacer(),
            if (widget.canApprove && status == 'pending')
              FilledButton.icon(key: const Key('gm-approve'), style: FilledButton.styleFrom(backgroundColor: green), onPressed: _busy ? null : () => _act('approve'),
                  icon: const Icon(Icons.check), label: const Text('Approve')),
            if (widget.canApprove && status == 'failed')
              FilledButton.icon(key: const Key('gm-retry'), onPressed: _busy ? null : () => _act('retry'), icon: const Icon(Icons.refresh), label: const Text('Retry')),
          ]),
        ]),
      ),
    );
  }
}

/// Pick a category for the photos/videos and when they go up, then upload them one by one.
class UploadMediaScreen extends StatefulWidget {
  const UploadMediaScreen({super.key, required this.clientId, required this.files, required this.categories});
  final int clientId;
  final List<PickedMedia> files;
  final List<Map<String, dynamic>> categories;

  @override
  State<UploadMediaScreen> createState() => _UploadMediaScreenState();
}

class _UploadMediaScreenState extends State<UploadMediaScreen> {
  String _category = 'ADDITIONAL';
  late String _when = widget.files.length > 1 ? 'spread' : 'now';
  int _done = 0;
  bool _busy = false;
  final _errors = <String>[];

  @override
  void initState() {
    super.initState();
    if (widget.categories.any((c) => c['key'] == 'EXTERIOR')) _category = 'EXTERIOR';
  }

  Future<void> _upload() async {
    final api = context.read<Session>().api;
    setState(() {
      _busy = true;
      _done = 0;
    });
    _errors.clear();
    for (final f in widget.files) {
      try {
        await api.upload('/api/clients/${widget.clientId}/google-media', {'category': _category, 'when': _when},
            field: 'file', bytes: f.bytes, filename: f.name);
        if (mounted) setState(() => _done++);
      } on ApiException catch (e) {
        _errors.add('${f.name}: ${e.message}');
      }
    }
    if (!mounted) return;
    setState(() => _busy = false);
    if (_errors.isEmpty) {
      Navigator.pop(context, _done);
    } else {
      await showDialog<void>(
        context: context,
        builder: (d) => AlertDialog(
          title: Text(_done == 0 ? 'Nothing was added' : '$_done added, ${_errors.length} not added'),
          content: Text(_errors.join('\n\n')),
          actions: [TextButton(onPressed: () => Navigator.pop(d), child: const Text('OK'))],
        ),
      );
      if (mounted && _done > 0) Navigator.pop(context, _done);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final n = widget.files.length;
    return Scaffold(
      appBar: navyBar('Upload to Google', subtitle: '$n ${n == 1 ? 'item' : 'items'} selected'),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        SizedBox(
          height: 96,
          child: ListView.separated(
            scrollDirection: Axis.horizontal,
            itemCount: n,
            separatorBuilder: (_, _) => const SizedBox(width: 8),
            itemBuilder: (_, i) {
              final f = widget.files[i];
              return ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: SizedBox(
                  width: 96,
                  child: f.video
                      ? const ColoredBox(color: Colors.black87, child: Icon(Icons.videocam, color: Colors.white, size: 32))
                      : Image.memory(Uint8List.fromList(f.bytes), fit: BoxFit.cover, errorBuilder: (_, _, _) => const Icon(Icons.image_outlined)),
                ),
              );
            },
          ),
        ),
        const SizedBox(height: 18),
        Text('What is it?', style: t.titleSmall),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final c in widget.categories)
            ChoiceChip(
              key: Key('cat-${c['key']}'),
              label: Text(c['label'] as String),
              avatar: Icon(categoryIcon(c['icon'] as String?), size: 18),
              selected: _category == c['key'],
              onSelected: _busy ? null : (_) => setState(() => _category = c['key'] as String),
            ),
        ]),
        const SizedBox(height: 18),
        Text('When should it go up?', style: t.titleSmall),
        RadioGroup<String>(
          groupValue: _when,
          onChanged: (v) => _busy ? null : setState(() => _when = v!),
          child: Column(children: [
            const RadioListTile<String>(key: Key('when-now'), contentPadding: EdgeInsets.zero, value: 'now', title: Text('Now'),
                subtitle: Text('Goes up on your Google profile in a minute')),
            RadioListTile<String>(key: const Key('when-spread'), contentPadding: EdgeInsets.zero, value: 'spread', title: const Text('One a day'),
                subtitle: Text(n > 1 ? 'Fresh photos every day for the next $n days' : 'On the next day without a new photo')),
          ]),
        ),
        Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(color: green.withValues(alpha: .1), borderRadius: BorderRadius.circular(10)),
          child: const Row(children: [
            Icon(Icons.eco_outlined, color: green, size: 18),
            SizedBox(width: 8),
            Expanded(child: Text('Fresh photos can get you up to 25% more calls', style: TextStyle(color: green))),
          ]),
        ),
      ]),
      bottomNavigationBar: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 10),
          child: GradientButton(
            key: const Key('gm-upload'),
            label: _busy ? 'Uploading $_done of $n…' : (n == 1 ? 'Upload' : 'Upload $n'),
            icon: Icons.cloud_upload,
            busy: _busy,
            onPressed: _upload,
          ),
        ),
      ),
    );
  }
}

IconData categoryIcon(String? name) => switch (name) {
      'storefront' => Icons.storefront_outlined,
      'chair' => Icons.chair_outlined,
      'shopping_bag' => Icons.shopping_bag_outlined,
      'handyman' => Icons.handyman_outlined,
      'restaurant' => Icons.restaurant_outlined,
      'weekend' => Icons.weekend_outlined,
      'groups' => Icons.groups_outlined,
      _ => Icons.add_photo_alternate_outlined,
    };

/// "Where it will upload?": a sketch of the Google Maps listing their photos appear on.
Future<void> showWhereItUploads(BuildContext context, String business, List<Map<String, dynamic>> items) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (s) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text.rich(
              TextSpan(children: [
                TextSpan(text: 'This Media Will be Uploaded on Your\n'),
                TextSpan(text: 'G', style: TextStyle(color: Color(0xFF4285F4))),
                TextSpan(text: 'o', style: TextStyle(color: Color(0xFFEA4335))),
                TextSpan(text: 'o', style: TextStyle(color: Color(0xFFFBBC05))),
                TextSpan(text: 'g', style: TextStyle(color: Color(0xFF4285F4))),
                TextSpan(text: 'l', style: TextStyle(color: Color(0xFF34A853))),
                TextSpan(text: 'e', style: TextStyle(color: Color(0xFFEA4335))),
                TextSpan(text: ' Profile'),
              ]),
              textAlign: TextAlign.center,
              style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700, height: 1.3),
            ),
            const SizedBox(height: 14),
            _MapsListing(business: business, thumbs: [for (final m in items.take(3)) m['thumb_url'] as String]),
            const SizedBox(height: 14),
            Container(
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(color: green.withValues(alpha: .1), borderRadius: BorderRadius.circular(10)),
              child: const Row(children: [
                Icon(Icons.eco_outlined, color: green, size: 18),
                SizedBox(width: 8),
                Expanded(
                  child: Text.rich(TextSpan(children: [
                    TextSpan(text: 'Fresh photos can get you up to '),
                    TextSpan(text: '25% more calls', style: TextStyle(fontWeight: FontWeight.w700)),
                  ]), style: TextStyle(color: green)),
                ),
              ]),
            ),
            const SizedBox(height: 12),
            GradientButton(key: const Key('got-it'), label: 'Got It', icon: Icons.thumb_up_alt_outlined, onPressed: () => Navigator.pop(s)),
          ]),
        ),
      ),
    );

class _MapsListing extends StatelessWidget {
  const _MapsListing({required this.business, required this.thumbs});
  final String business;
  final List<String> thumbs;

  @override
  Widget build(BuildContext context) {
    Widget chip(String t) => Container(
          margin: const EdgeInsets.only(right: 6),
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(color: const Color(0xFFE8EEF7), borderRadius: BorderRadius.circular(6)),
          child: Text(t, style: const TextStyle(fontSize: 11)),
        );
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: Colors.black87, width: 5),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Row(children: [
          Icon(Icons.location_on, color: Color(0xFFEA4335), size: 18),
          SizedBox(width: 4),
          Text('Google Maps', style: TextStyle(fontWeight: FontWeight.w600, color: Colors.black54)),
        ]),
        const SizedBox(height: 8),
        Row(children: [chip('Distance'), chip('Open now'), chip('Top rated')]),
        const SizedBox(height: 10),
        Text(business.isEmpty ? 'Your Business' : business, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: Colors.black87)),
        const Row(children: [
          Text('4.8 ', style: TextStyle(fontSize: 12, color: Colors.black87)),
          Icon(Icons.star, size: 13, color: Color(0xFFFBBC05)),
          Text(' · Open · Closes 9 pm', style: TextStyle(fontSize: 12, color: Colors.black54)),
        ]),
        const SizedBox(height: 8),
        SizedBox(
          height: 84,
          child: Row(children: [
            for (var i = 0; i < 3; i++)
              Expanded(
                child: Container(
                  margin: EdgeInsets.only(right: i < 2 ? 6 : 0),
                  clipBehavior: Clip.antiAlias,
                  decoration: BoxDecoration(
                    borderRadius: BorderRadius.circular(8),
                    border: i == 0 ? Border.all(color: green, width: 2.5) : null,
                    color: const Color(0xFFDDE5EE),
                  ),
                  child: i < thumbs.length
                      ? Image.network(thumbs[i], fit: BoxFit.cover, errorBuilder: (_, _, _) => const Icon(Icons.image_outlined, color: Colors.black38))
                      : Icon(i == 0 ? Icons.add_a_photo_outlined : Icons.image_outlined, color: Colors.black38),
                ),
              ),
          ]),
        ),
        const SizedBox(height: 4),
        const Text('Your photos show here, where customers decide to call or visit', style: TextStyle(fontSize: 11, color: Colors.black54)),
      ]),
    );
  }
}

/// "What to upload?": the kinds of photos Google shows, swipeable, with what each is for.
Future<void> showWhatToUpload(BuildContext context, List<Map<String, dynamic>> categories) => showModalBottomSheet<void>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _WhatToUpload(categories: categories),
    );

class _WhatToUpload extends StatefulWidget {
  const _WhatToUpload({required this.categories});
  final List<Map<String, dynamic>> categories;

  @override
  State<_WhatToUpload> createState() => _WhatToUploadState();
}

class _WhatToUploadState extends State<_WhatToUpload> {
  final _pages = PageController(viewportFraction: .78);
  int _page = 0;

  static const _tints = [Color(0xFF3B5BDB), Color(0xFFB04DE8), Color(0xFFE8457C), Color(0xFF2E9E5B), Color(0xFFFF7A2F), Color(0xFF1098AD),
    Color(0xFF7048E8), Color(0xFF495057)];

  @override
  void dispose() {
    _pages.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cats = widget.categories;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.only(bottom: 16),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('What to upload?', style: TextStyle(fontSize: 19, fontWeight: FontWeight.w700)),
          const SizedBox(height: 2),
          const Text('You can upload both photos & videos', style: TextStyle(color: Colors.black54)),
          const SizedBox(height: 14),
          SizedBox(
            height: 300,
            child: PageView.builder(
              key: const Key('what-carousel'),
              controller: _pages,
              itemCount: cats.length,
              onPageChanged: (i) => setState(() => _page = i),
              itemBuilder: (_, i) {
                final c = cats[i];
                final tint = _tints[i % _tints.length];
                return Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 6),
                  child: Card(
                    clipBehavior: Clip.antiAlias,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      Expanded(
                        child: DecoratedBox(
                          decoration: BoxDecoration(gradient: LinearGradient(colors: [tint.withValues(alpha: .85), tint.withValues(alpha: .45)],
                              begin: Alignment.topLeft, end: Alignment.bottomRight)),
                          child: Icon(categoryIcon(c['icon'] as String?), size: 72, color: Colors.white),
                        ),
                      ),
                      Padding(
                        padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(c['label'] as String, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15)),
                          const SizedBox(height: 4),
                          Text(c['tip'] as String, maxLines: 3, overflow: TextOverflow.ellipsis, style: const TextStyle(color: Colors.black54, fontSize: 12.5)),
                        ]),
                      ),
                    ]),
                  ),
                );
              },
            ),
          ),
          const SizedBox(height: 10),
          Row(mainAxisAlignment: MainAxisAlignment.center, children: [
            for (var i = 0; i < cats.length; i++)
              Container(
                width: 7,
                height: 7,
                margin: const EdgeInsets.symmetric(horizontal: 3),
                decoration: BoxDecoration(shape: BoxShape.circle, color: i == _page ? red : Colors.black26),
              ),
          ]),
          const SizedBox(height: 12),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: GradientButton(key: const Key('what-got-it'), label: 'Got It', icon: Icons.thumb_up_alt_outlined, onPressed: () => Navigator.pop(context)),
          ),
        ]),
      ),
    );
  }
}
