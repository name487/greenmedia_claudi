import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../../api/api_client.dart';
import '../../state/session.dart';
import 'create_flow.dart';
import 'shared.dart';

/// Pick a product to turn into an AI post (poster + caption), or add a new one.
class ItemsScreen extends StatefulWidget {
  const ItemsScreen({super.key, required this.clientId});
  final int clientId;

  @override
  State<ItemsScreen> createState() => _ItemsScreenState();
}

class _ItemsScreenState extends State<ItemsScreen> {
  List<Map<String, dynamic>>? _items;
  int? _making;

  ApiClient get _api => context.read<Session>().api;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final d = await _api.get('/api/clients/${widget.clientId}/items') as Map<String, dynamic>;
    if (mounted) setState(() => _items = (d['items'] as List).cast<Map<String, dynamic>>());
  }

  Future<void> _add() async {
    await Navigator.push(context, MaterialPageRoute<void>(builder: (_) => AddItemScreen(clientId: widget.clientId)));
    _load();
  }

  Future<void> _make(Map<String, dynamic> item) async {
    setState(() => _making = item['id'] as int);
    try {
      final post = await _api.post('/api/clients/${widget.clientId}/ai-posts/poster', {'item_id': item['id']}) as Map<String, dynamic>;
      if (!mounted) return;
      await Navigator.pushReplacement(context, MaterialPageRoute<void>(builder: (_) => PostReviewScreen(clientId: widget.clientId, post: post)));
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _making = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final items = _items;
    return Scaffold(
      appBar: navyBar('Select Item', subtitle: context.read<Session>().me!.clientName),
      body: items == null
          ? const Center(child: CircularProgressIndicator())
          : items.isEmpty
              ? Center(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      const Text('No items yet. Add your first product to create a poster.', textAlign: TextAlign.center),
                      const SizedBox(height: 14),
                      SizedBox(width: 200, child: GradientButton(key: const Key('add-item'), label: 'Add New Item', onPressed: _add)),
                    ]),
                  ),
                )
              : Column(children: [
                  const Padding(padding: EdgeInsets.fromLTRB(12, 12, 12, 0), child: Text('Tap a product to create an AI post with it')),
                  Expanded(
                    child: GridView.builder(
                      padding: const EdgeInsets.all(12),
                      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(crossAxisCount: 2, mainAxisSpacing: 10, crossAxisSpacing: 10, childAspectRatio: .78),
                      itemCount: items.length,
                      itemBuilder: (context, i) {
                        final it = items[i];
                        return InkWell(
                          key: Key('item-${it['id']}'),
                          borderRadius: BorderRadius.circular(12),
                          onTap: _making == null ? () => _make(it) : null,
                          child: Card(
                            margin: EdgeInsets.zero,
                            clipBehavior: Clip.antiAlias,
                            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                              Expanded(
                                child: Stack(fit: StackFit.expand, children: [
                                  Image.network(it['image_url'] as String, fit: BoxFit.cover, errorBuilder: (_, _, _) => const Icon(Icons.image_outlined)),
                                  if (_making == it['id']) const ColoredBox(color: Colors.black38, child: Center(child: CircularProgressIndicator(color: Colors.white))),
                                ]),
                              ),
                              Padding(
                                padding: const EdgeInsets.all(8),
                                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                                  Text(it['name'] as String, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w700)),
                                  if ((it['price_label'] as String? ?? '').isNotEmpty) Text(it['price_label'] as String, style: const TextStyle(color: green)),
                                ]),
                              ),
                            ]),
                          ),
                        );
                      },
                    ),
                  ),
                  SafeArea(
                    top: false,
                    child: Padding(padding: const EdgeInsets.fromLTRB(12, 0, 12, 10), child: OutlinedButton.icon(
                      key: const Key('add-item'),
                      style: OutlinedButton.styleFrom(minimumSize: const Size.fromHeight(46)),
                      icon: const Icon(Icons.add),
                      label: const Text('Add New Item'),
                      onPressed: _add,
                    )),
                  ),
                ]),
    );
  }
}

/// Item Image*, Item Name*, Description, Price.
class AddItemScreen extends StatefulWidget {
  const AddItemScreen({super.key, required this.clientId});
  final int clientId;

  /// Picks a photo; replaceable in tests. Returns (bytes, filename) or null.
  static Future<(List<int>, String)?> Function() pickPhoto = () async {
    final f = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 1600, imageQuality: 90);
    if (f == null) return null;
    return (await f.readAsBytes(), f.name);
  };

  @override
  State<AddItemScreen> createState() => _AddItemScreenState();
}

class _AddItemScreenState extends State<AddItemScreen> {
  final _name = TextEditingController(), _desc = TextEditingController(), _price = TextEditingController();
  (List<int>, String)? _photo;
  bool _busy = false;

  @override
  void dispose() {
    _name.dispose();
    _desc.dispose();
    _price.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final p = await AddItemScreen.pickPhoto();
    if (p != null && mounted) setState(() => _photo = p);
  }

  Future<void> _save() async {
    if (_photo == null || _name.text.trim().length < 2) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Add a photo and a name')));
      return;
    }
    setState(() => _busy = true);
    try {
      await context.read<Session>().api.upload('/api/clients/${widget.clientId}/items',
          {'name': _name.text.trim(), 'description': _desc.text.trim(), 'price': _price.text.trim()},
          field: 'image', bytes: _photo!.$1, filename: _photo!.$2);
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message), backgroundColor: Colors.red.shade700));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: navyBar('Add New Item'),
      body: ListView(padding: const EdgeInsets.all(16), children: [
        Text('Item Image*', style: t.labelLarge),
        const SizedBox(height: 6),
        InkWell(
          key: const Key('pick-photo'),
          onTap: _pick,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            height: 180,
            decoration: BoxDecoration(border: Border.all(color: Theme.of(context).dividerColor), borderRadius: BorderRadius.circular(12)),
            clipBehavior: Clip.antiAlias,
            child: _photo == null
                ? const Center(child: Column(mainAxisSize: MainAxisSize.min, children: [Icon(Icons.cloud_upload_outlined, size: 36), Text('Tap to add a photo')]))
                : Image.memory(Uint8List.fromList(_photo!.$1), fit: BoxFit.cover),
          ),
        ),
        const SizedBox(height: 14),
        TextField(key: const Key('item-name'), controller: _name, decoration: const InputDecoration(labelText: 'Item Name*', hintText: 'Add your item name')),
        const SizedBox(height: 10),
        TextField(controller: _desc, maxLines: 3, decoration: const InputDecoration(labelText: 'Description (Optional)', hintText: 'Add your item description')),
        const SizedBox(height: 10),
        TextField(controller: _price, keyboardType: TextInputType.number, decoration: const InputDecoration(labelText: 'Price (Optional)', hintText: 'Add your item price', prefixText: '₹ ')),
        const SizedBox(height: 20),
        GradientButton(key: const Key('save-item'), label: 'Save Item', busy: _busy, onPressed: _save),
      ]),
    );
  }
}
